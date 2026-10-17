# Sistem Klasterisasi Pola Hafalan Al-Qur’an Santri

Prototype web sesuai rancangan halaman pada Bab III proposal skripsi, Gambar 3.12 hingga Gambar 3.17. Implementasi empat variabel menggunakan **K-Medoids (PAM)**, **Min-Max**, **Euclidean Distance**, **Silhouette Score**, dan **Davies-Bouldin Index**.

## Empat variabel tetap

1. X1 = `setoran`, jumlah setoran dalam rentang periode, dijumlahkan antarre-kap bulanan.
2. X2 = `murojaah`, jumlah murojaah dalam rentang periode, dijumlahkan.
3. X3 = `hafalan_tercapai`, capaian hafalan dalam **juz (0 sampai 30)**, dirata-ratakan dalam rentang periode karena merupakan capaian kumulatif yang direkam bulanan (tidak dijumlahkan).
4. X4 = `kehadiran`, persentase absensi (0 sampai 100), dirata-ratakan dalam rentang periode.

**Catatan metodologi:** Untuk X3 digunakan rerata capaian selama periode. Jika yang dikehendaki nilai posisi pada *bulan terakhir*, modifikasi fungsi `aggregate` di `server.py` dan jelaskan pilihan itu dalam laporan. Empat variabel wajib selalu aktif, seperti disepakati untuk implementasi ini.

## Mulai dengan SQLite (mode uji cepat)

Persyaratan: Python 3.10 atau lebih baru.

```bash
python -m pip install -r requirements.txt
python server.py
```

Buka `http://127.0.0.1:8000`. Pada pembuatan database kosong, akun awal `admin` dengan sandi `Admin@12345`. Sebaiknya gunakan variabel lingkungan `ADMIN_PASSWORD` sebelum pertama kali menjalankan server dan ganti sandi awal melalui dashboard. Data SQLite tersimpan pada `data/tahfidz.db`.

## Mulai dengan MySQL (sesuai proposal)

Pastikan MySQL Server 8.0+ aktif dan jalankan perintah di mysql CLI atau phpMyAdmin:

```sql
CREATE DATABASE tahfidz_kmedoids CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Di PowerShell Windows, dari direktori proyek:

```powershell
$env:DB_ENGINE="mysql"
$env:MYSQL_HOST="127.0.0.1"
$env:MYSQL_PORT="3306"
$env:MYSQL_DATABASE="tahfidz_kmedoids"
$env:MYSQL_USER="root"
$env:MYSQL_PASSWORD="PASSWORD_MYSQL_ANDA"
$env:ADMIN_PASSWORD="GantiPasswordAwalYangPanjang123!"
python server.py
```

Skema tabel `schema_mysql.sql` otomatis dibuat saat startup. Tidak perlu menjalankan skema itu secara manual jika database sudah dibuat. **Mode MySQL belum diuji dengan server MySQL langsung dalam lingkungan pengerjaan ini.** Mode SQLite dan algoritma diuji otomatis.

## Enam halaman sesuai proposal

- Login, Gambar 3.12
- Dashboard, Gambar 3.13
- Data Santri (CRUD), Gambar 3.14
- Rekap Hafalan (CRUD dan impor CSV), Gambar 3.15
- Proses Klasterisasi (pemilihan rentang periode dan K), Gambar 3.16
- Hasil Klasterisasi (cluster, DBI, Silhouette, anggota, ekspor CSV), Gambar 3.17

Navigasi, formulir, dan elemen dashboard memakai versi visual responsif yang mengadaptasi struktur wireframe proposal. Tidak mengklaim identik piksel dengan wireframe yang disisipkan dalam dokumen.

## Input CSV

Header wajib: `nis,nama,kelas,bulan,setoran,murojaah,hafalan_tercapai,kehadiran` (`kelas` opsional). Contoh tersedia di `data/contoh_rekap_simulasi.csv` dan tombol **Unduh Template** pada halaman Rekap Hafalan. Input harus bersumber dari data yang diizinkan oleh pesantren. Sampel disediakan hanya untuk uji, bukan hasil penelitian.

## Cara demo

1. Login, ganti password.
2. Masukkan identitas santri, atau impor contoh CSV.
3. Lihat dan koreksi rekap hafalan, termasuk jumlah hafalan tercapai (juz).
4. Pilih periode dan K pada menu Proses Klasterisasi, klik pratinjau dan jalankan.
5. Lihat nilai Silhouette Score, DBI, karakteristik kelompok, serta ekspor hasil.
6. Dokumentasikan kondisi data kosong, kesalahan input, status loading, dan output aktual.

## Pengujian

```bash
python -m unittest discover -s tests -v
```

Penting: clustering menghasilkan **pengelompokan**, bukan prediksi prestasi. Silhouette dan DBI bukan ukuran akurasi prediksi. Nomor cluster bukan ranking kualitas santri. Hasil harus diinterpretasikan bersama pembimbing tahfidz.

## Catatan implementasi

- Server HTTP Python mandiri: cocok sebagai prototype *lokal*, bukan aplikasi produksi terbuka internet.
- Sesi tersimpan di memori dan tidak bertahan setelah restart server.
- Pertimbangkan deployment dengan framework teruji, pembatasan login, HTTPS, audit akses, pembatasan izin data, dan backup sebelum menangani data asli santri.
- Saat menggunakan MySQL, sediakan akun aplikasi database dengan hak akses minimum, bukan akun root untuk produksi.
