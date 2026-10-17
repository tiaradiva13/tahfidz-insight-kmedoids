"""Standalone web app. Run with: python server.py (Python 3.10+, numpy, scikit-learn)."""
import csv, datetime as dt, hashlib, hmac, io, json, os, secrets, sqlite3, time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from clustering import cluster

ROOT=Path(__file__).resolve().parent
DB=Path(os.getenv('DB_PATH',str(ROOT/'data'/'tahfidz.db')))
SESSIONS={}
MAX_BODY=2_000_000

try:
    from pymysql.err import IntegrityError as MYSQL_INTEGRITY_ERROR
except ImportError:
    class MYSQL_INTEGRITY_ERROR(Exception):pass
DB_ENGINE=os.getenv('DB_ENGINE','sqlite').lower()

class MySQLRow(dict):
    def __getitem__(self,key):
        if isinstance(key,int):return list(self.values())[key]
        return super().__getitem__(key)

class MySQLResult:
    def __init__(self,cursor):self.cursor=cursor;self.lastrowid=cursor.lastrowid
    def fetchone(self):
        r=self.cursor.fetchone();return MySQLRow(r) if r is not None else None
    def fetchall(self):return [MySQLRow(x) for x in self.cursor.fetchall()]

class MySQLConnection:
    def __init__(self):
        try:import pymysql
        except ImportError:raise RuntimeError('Untuk MySQL instal: pip install pymysql')
        self.db=pymysql.connect(host=os.getenv('MYSQL_HOST','127.0.0.1'),port=int(os.getenv('MYSQL_PORT','3306')),
            user=os.getenv('MYSQL_USER','root'),password=os.getenv('MYSQL_PASSWORD',''),database=os.getenv('MYSQL_DATABASE','tahfidz_kmedoids'),
            charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    def __enter__(self):return self
    def __exit__(self,typ,val,tb):
        try:
            if typ is None:self.db.commit()
            else:self.db.rollback()
        finally:self.db.close()
    def executescript(self,sql):
        for stmt in sql.split(';'):
            if stmt.strip():self.execute(stmt)
    def execute(self,sql,args=()):
        import re
        sql=sql.replace('?', '%s')
        sql=sql.replace('INSERT INTO santri(nis,nama,kelas) VALUES(%s,%s,%s) ON CONFLICT(nis) DO UPDATE SET nama=excluded.nama,kelas=excluded.kelas',
          'INSERT INTO santri(nis,nama,kelas) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE nama=VALUES(nama),kelas=VALUES(kelas)')
        sql=sql.replace('ON CONFLICT(santri_id,bulan) DO UPDATE SET setoran=excluded.setoran,murojaah=excluded.murojaah,hafalan_tercapai=excluded.hafalan_tercapai,kehadiran=excluded.kehadiran',
          'ON DUPLICATE KEY UPDATE setoran=VALUES(setoran),murojaah=VALUES(murojaah),hafalan_tercapai=VALUES(hafalan_tercapai),kehadiran=VALUES(kehadiran)')
        cur=self.db.cursor();cur.execute(sql,args);return MySQLResult(cur)

def connection():
    if DB_ENGINE=='mysql':return MySQLConnection()
    DB.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB,timeout=15)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con

def hash_pw(password,salt=None):
    salt=salt or secrets.token_hex(16)
    derived=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),300000).hex()
    return salt+'$'+derived

def check_pw(password,stored):
    try:
        salt,digest=stored.split('$'); return hmac.compare_digest(hash_pw(password,salt).split('$')[1],digest)
    except (ValueError,AttributeError): return False

def init_db():
    with connection() as con:
        if DB_ENGINE=='mysql':
            con.executescript((ROOT/'schema_mysql.sql').read_text(encoding='utf-8'))
        else: con.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'admin');
        CREATE TABLE IF NOT EXISTS santri(id INTEGER PRIMARY KEY AUTOINCREMENT, nis TEXT UNIQUE NOT NULL, nama TEXT NOT NULL, kelas TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS rekap(id INTEGER PRIMARY KEY AUTOINCREMENT, santri_id INTEGER NOT NULL REFERENCES santri(id) ON DELETE CASCADE, bulan TEXT NOT NULL, setoran INTEGER NOT NULL CHECK(setoran>=0), murojaah INTEGER NOT NULL CHECK(murojaah>=0), hafalan_tercapai REAL NOT NULL CHECK(hafalan_tercapai BETWEEN 0 AND 30), kehadiran REAL NOT NULL CHECK(kehadiran BETWEEN 0 AND 100), UNIQUE(santri_id,bulan));
        CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, start_month TEXT NOT NULL, end_month TEXT NOT NULL, k INTEGER NOT NULL, metrics_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS run_items(run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE, santri_id INTEGER NOT NULL REFERENCES santri(id) ON DELETE CASCADE, cluster INTEGER NOT NULL, setoran REAL NOT NULL, murojaah REAL NOT NULL, hafalan_tercapai REAL NOT NULL, kehadiran REAL NOT NULL, PRIMARY KEY(run_id,santri_id));
        ''')
        if not con.execute('SELECT 1 FROM users').fetchone():
            passwd=os.getenv('ADMIN_PASSWORD') or 'Admin@12345'
            con.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',('admin',hash_pw(passwd),'admin'))
            if not os.getenv('ADMIN_PASSWORD'): print('PERINGATAN: password awal admin Admin@12345. Ubah segera setelah masuk.')

def rows(cur): return [dict(r) for r in cur.fetchall()]
def validate_month(value):
    if not isinstance(value,str) or len(value)!=7: raise ValueError('Format periode harus YYYY-MM.')
    try: dt.datetime.strptime(value,'%Y-%m')
    except ValueError: raise ValueError('Periode tidak valid.')
    return value

def positive_int(value,label):
    if isinstance(value,bool) or str(value).strip()=='' : raise ValueError(f'{label} wajib diisi.')
    n=int(value)
    if n<0: raise ValueError(f'{label} tidak boleh negatif.')
    return n

def validate_rekap(data):
    sid=positive_int(data.get('santri_id'),'Santri')
    bulan=validate_month(data.get('bulan'))
    s=positive_int(data.get('setoran'),'Setoran'); m=positive_int(data.get('murojaah'),'Murojaah')
    h=float(data.get('hafalan_tercapai'))
    if not 0<=h<=30: raise ValueError('Hafalan tercapai harus 0 sampai 30 juz.')
    a=float(data.get('kehadiran'))
    if not 0<=a<=100: raise ValueError('Kehadiran harus 0 sampai 100 persen.')
    return sid,bulan,s,m,h,a

def aggregate(con,start,end):
    # Include only students with at least one record in the selected range.
    return rows(con.execute('''SELECT s.id,s.nis,s.nama,s.kelas, SUM(r.setoran) AS setoran, SUM(r.murojaah) AS murojaah, ROUND(AVG(r.hafalan_tercapai),2) AS hafalan_tercapai,
      ROUND(AVG(r.kehadiran),2) AS kehadiran, COUNT(*) AS jumlah_bulan
      FROM rekap r JOIN santri s ON s.id=r.santri_id WHERE r.bulan BETWEEN ? AND ?
      GROUP BY s.id ORDER BY s.nama,s.id''',(start,end)))

class Handler(BaseHTTPRequestHandler):
    server_version='TahfidzPrototype/1.0'
    def send_json(self,obj,status=200,cookie=None):
        data=json.dumps(obj,ensure_ascii=False,allow_nan=False,default=str).encode()
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(data)
    def send_bytes(self,blob,mime,filename=None):
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(blob)))
        self.send_header('X-Content-Type-Options','nosniff')
        if filename:self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers();self.wfile.write(blob)
    def session(self):
        c=SimpleCookie()
        try:c.load(self.headers.get('Cookie',''))
        except Exception:return None
        sid=c.get('sid')
        if not sid:return None
        token=sid.value; sess=SESSIONS.get(token)
        if not sess or sess['expiry']<time.time():SESSIONS.pop(token,None);return None
        return sess
    def body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size>MAX_BODY:raise ValueError('Ukuran permintaan terlalu besar.')
        return json.loads(self.rfile.read(size) or b'{}')
    def require_auth(self,write=False):
        sess=self.session()
        if not sess: self.send_json({'error':'Sesi berakhir. Silakan login.'},401);return False
        if write and self.headers.get('X-CSRF-Token')!=sess['csrf']:
            self.send_json({'error':'Token keamanan tidak valid.'},403);return False
        return True
    def do_GET(self): self.dispatch('GET')
    def do_POST(self): self.dispatch('POST')
    def do_PUT(self): self.dispatch('PUT')
    def do_DELETE(self): self.dispatch('DELETE')
    def dispatch(self,method):
        path=urlparse(self.path).path
        try:
            if path=='/' or path=='/index.html':return self.serve_static('index.html')
            if path.startswith('/static/') and method=='GET':return self.serve_static(path[8:])
            if path=='/api/login' and method=='POST':
                body=self.body()
                with connection() as con: user=con.execute('SELECT * FROM users WHERE username=?',(str(body.get('username','')),)).fetchone()
                if not user or not check_pw(str(body.get('password','')),user['password_hash']):return self.send_json({'error':'Username atau password salah.'},401)
                token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
                SESSIONS[token]={'id':user['id'],'name':user['username'],'role':user['role'],'csrf':csrf,'expiry':time.time()+28800}
                return self.send_json({'username':user['username'],'csrf':csrf},cookie=f'sid={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
            if path=='/api/session' and method=='GET':
                sess=self.session();return self.send_json({'logged_in':bool(sess),'username':sess['name'] if sess else None,'csrf':sess['csrf'] if sess else None})
            if not path.startswith('/api/'):return self.send_json({'error':'Halaman tidak ditemukan.'},404)
            if not self.require_auth(method!='GET'):return
            if path=='/api/logout' and method=='POST':
                c=SimpleCookie();c.load(self.headers.get('Cookie',''));sid=c.get('sid')
                if sid:SESSIONS.pop(sid.value,None)
                return self.send_json({'ok':True},cookie='sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            with connection() as con:
                if path=='/api/summary' and method=='GET':
                    return self.send_json({'santri':con.execute('SELECT COUNT(*) FROM santri').fetchone()[0],'rekap':con.execute('SELECT COUNT(*) FROM rekap').fetchone()[0],'runs':con.execute('SELECT COUNT(*) FROM runs').fetchone()[0]})
                if path=='/api/santri':
                    if method=='GET':return self.send_json(rows(con.execute('SELECT * FROM santri ORDER BY nama,id')))
                    if method=='POST':
                        b=self.body();nis=str(b.get('nis','')).strip();nama=str(b.get('nama','')).strip();kelas=str(b.get('kelas','')).strip()
                        if not nis or not nama or len(nis)>40 or len(nama)>120:raise ValueError('NIS dan nama wajib diisi (maks. 40 dan 120 karakter).')
                        cur=con.execute('INSERT INTO santri(nis,nama,kelas) VALUES(?,?,?)',(nis,nama,kelas));return self.send_json({'id':cur.lastrowid},201)
                if path.startswith('/api/santri/'):
                    sid=positive_int(path.rsplit('/',1)[-1],'ID')
                    if method=='DELETE':con.execute('DELETE FROM santri WHERE id=?',(sid,));return self.send_json({'ok':True})
                    if method=='PUT':
                        b=self.body();nis=str(b.get('nis','')).strip();nama=str(b.get('nama','')).strip();kelas=str(b.get('kelas','')).strip()
                        if not nis or not nama:raise ValueError('NIS dan nama wajib diisi.')
                        con.execute('UPDATE santri SET nis=?, nama=?, kelas=? WHERE id=?',(nis,nama,kelas,sid));return self.send_json({'ok':True})
                if path=='/api/rekap':
                    if method=='GET':return self.send_json(rows(con.execute('SELECT r.*,s.nama,s.nis FROM rekap r JOIN santri s ON s.id=r.santri_id ORDER BY r.bulan DESC,s.nama')))
                    if method=='POST':
                        fields=validate_rekap(self.body());cur=con.execute('INSERT INTO rekap(santri_id,bulan,setoran,murojaah,hafalan_tercapai,kehadiran) VALUES(?,?,?,?,?,?)',fields)
                        return self.send_json({'id':cur.lastrowid},201)
                if path.startswith('/api/rekap/'):
                    rid=positive_int(path.rsplit('/',1)[-1],'ID')
                    if method=='DELETE':con.execute('DELETE FROM rekap WHERE id=?',(rid,));return self.send_json({'ok':True})
                    if method=='PUT':
                        fields=validate_rekap(self.body());con.execute('UPDATE rekap SET santri_id=?,bulan=?,setoran=?,murojaah=?,hafalan_tercapai=?,kehadiran=? WHERE id=?',(*fields,rid));return self.send_json({'ok':True})
                if path=='/api/import' and method=='POST':
                    b=self.body();payload=b.get('csv','')
                    if not isinstance(payload,str) or len(payload)>MAX_BODY:raise ValueError('CSV tidak valid.')
                    reader=csv.DictReader(io.StringIO(payload.lstrip('\ufeff')))
                    if not {'nis','nama','bulan','setoran','murojaah','hafalan_tercapai','kehadiran'}.issubset(reader.fieldnames or []):raise ValueError('Kolom wajib: nis,nama,bulan,setoran,murojaah,hafalan_tercapai,kehadiran. Opsional: kelas.')
                    processed=0
                    for row in reader:
                        nis=(row.get('nis') or '').strip();nama=(row.get('nama') or '').strip()
                        if not nis or not nama:raise ValueError(f'Baris {processed+2}: NIS dan nama wajib diisi.')
                        con.execute('INSERT INTO santri(nis,nama,kelas) VALUES(?,?,?) ON CONFLICT(nis) DO UPDATE SET nama=excluded.nama,kelas=excluded.kelas',(nis,nama,(row.get('kelas') or '').strip()))
                        sid=con.execute('SELECT id FROM santri WHERE nis=?',(nis,)).fetchone()[0]
                        fields=validate_rekap({'santri_id':sid,**row})
                        con.execute('INSERT INTO rekap(santri_id,bulan,setoran,murojaah,hafalan_tercapai,kehadiran) VALUES(?,?,?,?,?,?) ON CONFLICT(santri_id,bulan) DO UPDATE SET setoran=excluded.setoran,murojaah=excluded.murojaah,hafalan_tercapai=excluded.hafalan_tercapai,kehadiran=excluded.kehadiran',fields)
                        processed+=1
                        if processed>5000:raise ValueError('Maksimal 5000 baris per impor.')
                    return self.send_json({'imported':processed})
                if path=='/api/preview' and method=='GET':
                    q=parse_qs(urlparse(self.path).query);start=validate_month(q.get('start',['2026-01'])[0]);end=validate_month(q.get('end',['2026-12'])[0]);return self.send_json(aggregate(con,start,end))
                if path=='/api/cluster' and method=='POST':
                    b=self.body();start=validate_month(b.get('start'));end=validate_month(b.get('end'))
                    if start>end:raise ValueError('Periode awal harus sebelum atau sama dengan periode akhir.')
                    k=positive_int(b.get('k'),'Jumlah cluster');dataset=aggregate(con,start,end)
                    result=cluster(dataset,k)
                    cur=con.execute('INSERT INTO runs(start_month,end_month,k,metrics_json) VALUES(?,?,?,?)',(start,end,k,json.dumps(result,ensure_ascii=False)))
                    run_id=cur.lastrowid
                    for record,label in zip(dataset,result['labels']):
                        con.execute('INSERT INTO run_items(run_id,santri_id,cluster,setoran,murojaah,hafalan_tercapai,kehadiran) VALUES(?,?,?,?,?,?,?)',(run_id,record['id'],label,record['setoran'],record['murojaah'],record['hafalan_tercapai'],record['kehadiran']))
                    return self.send_json({'id':run_id,**result},201)
                if path=='/api/runs' and method=='GET':return self.send_json(rows(con.execute('SELECT id,created_at,start_month,end_month,k FROM runs ORDER BY id DESC LIMIT 100')))
                if path.startswith('/api/runs/'):
                    parts=path.split('/');rid=positive_int(parts[3],'ID')
                    run=con.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
                    if not run:return self.send_json({'error':'Hasil tidak ditemukan.'},404)
                    items=rows(con.execute('SELECT i.*,s.nama,s.nis,s.kelas FROM run_items i JOIN santri s ON s.id=i.santri_id WHERE run_id=? ORDER BY cluster,nama',(rid,)))
                    if len(parts)==5 and parts[4]=='export' and method=='GET':
                        buff=io.StringIO();writer=csv.writer(buff);writer.writerow(['nis','nama','kelas','cluster','setoran','murojaah','hafalan_tercapai','kehadiran'])
                        for x in items:writer.writerow([x[c] for c in ['nis','nama','kelas','cluster','setoran','murojaah','hafalan_tercapai','kehadiran']])
                        return self.send_bytes(('\ufeff'+buff.getvalue()).encode('utf-8'),'text/csv; charset=utf-8',f'hasil-klasterisasi-{rid}.csv')
                    if method=='GET':return self.send_json({'run':dict(run)|{'metrics':json.loads(run['metrics_json'])},'items':items})
                if path=='/api/password' and method=='POST':
                    b=self.body();old=str(b.get('old',''));new=str(b.get('new',''))
                    user=con.execute('SELECT * FROM users WHERE id=?',(self.session()['id'],)).fetchone()
                    if not check_pw(old,user['password_hash']):raise ValueError('Password lama tidak sesuai.')
                    if len(new)<10:raise ValueError('Password baru minimal 10 karakter.')
                    con.execute('UPDATE users SET password_hash=? WHERE id=?',(hash_pw(new),user['id']))
                    return self.send_json({'ok':True})
            self.send_json({'error':'Endpoint tidak ditemukan.'},404)
        except (ValueError,TypeError) as exc:self.send_json({'error':str(exc)},400)
        except (sqlite3.IntegrityError, MYSQL_INTEGRITY_ERROR) as exc:self.send_json({'error':'Data duplikat atau relasi tidak valid. Periksa NIS, santri, dan periode.'},409)
        except Exception as exc:
            import traceback;traceback.print_exc();self.send_json({'error':'Terjadi kesalahan internal. Periksa log server.'},500)
    def serve_static(self,name):
        if name not in ['index.html','style.css','app.js']:return self.send_json({'error':'File tidak ditemukan.'},404)
        data=(ROOT/'static'/name).read_bytes()
        mime={'index.html':'text/html; charset=utf-8','style.css':'text/css; charset=utf-8','app.js':'application/javascript; charset=utf-8'}[name]
        self.send_bytes(data,mime)

def main():
    init_db();port=int(os.getenv('PORT','8000'));host=os.getenv('HOST','127.0.0.1')
    print(f'Buka http://{host}:{port}');ThreadingHTTPServer((host,port),Handler).serve_forever()
if __name__=='__main__':main()
