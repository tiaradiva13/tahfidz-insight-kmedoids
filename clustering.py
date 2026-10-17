"""Deterministic partitioning-around-medoids, Euclidean metric, Min-Max scaling."""
import numpy as np
from sklearn.metrics import silhouette_score, davies_bouldin_score

def cluster(records, k, seed=42, max_iter=100):
    if len(records) < 3 or not 2 <= k < len(records):
        raise ValueError('Jumlah cluster harus minimal 2 dan kurang dari jumlah data (minimal 3 data).')
    raw = np.array([[float(r['setoran']), float(r['murojaah']), float(r['hafalan_tercapai']), float(r['kehadiran'])] for r in records], dtype=float)
    if not np.isfinite(raw).all(): raise ValueError('Data mengandung nilai tidak valid.')
    mn, mx = raw.min(axis=0), raw.max(axis=0)
    scaled = (raw-mn)/np.where(mx>mn,mx-mn,1)
    if np.unique(scaled,axis=0).shape[0] < k: raise ValueError('Jumlah variasi data tidak cukup untuk cluster yang dipilih.')
    dist = np.sqrt(((scaled[:,None,:]-scaled[None,:,:])**2).sum(axis=2))
    rng = np.random.default_rng(seed)
    n=len(records)
    medoids = list(map(int,rng.choice(n,size=k,replace=False)))
    def assign(m):
        labels=np.argmin(dist[:,m],axis=1)
        cost=float(np.min(dist[:,m],axis=1).sum())
        return labels,cost
    labels,cost=assign(medoids)
    iterations=0
    for _ in range(max_iter):
        best_cost=cost; best=None
        for i in range(k):
            for j in range(n):
                if j in medoids: continue
                candidate=medoids.copy();candidate[i]=j
                _,trial=assign(candidate)
                if trial < best_cost - 1e-10:
                    best_cost=trial; best=candidate
        if best is None: break
        medoids=best;labels,cost=assign(medoids);iterations+=1
    # Ensure representative data itself belongs to its cluster in zero-distance ties.
    labels,cost=assign(medoids)
    for i,m in enumerate(medoids): labels[m]=i
    counts=np.bincount(labels,minlength=k)
    if (counts == 0).any(): raise ValueError('Ada cluster kosong. Coba jumlah cluster atau dataset lain.')
    silhouette=None; dbi=None
    if len(set(labels))>=2 and len(set(labels))<n:
        silhouette=float(silhouette_score(scaled,labels,metric='euclidean'))
        dbi=float(davies_bouldin_score(scaled,labels))
    groups=[]
    for i in range(k):
        subset=raw[labels==i]
        groups.append({'cluster':int(i+1),'jumlah':int(len(subset)), 'rata_setoran':round(float(subset[:,0].mean()),2),'rata_murojaah':round(float(subset[:,1].mean()),2),'rata_hafalan_tercapai':round(float(subset[:,2].mean()),2),'rata_kehadiran':round(float(subset[:,3].mean()),2),'medoid_id':records[medoids[i]]['id']})
    return {'labels':[int(x+1) for x in labels], 'groups':groups, 'silhouette':round(silhouette,4) if silhouette is not None else None,'dbi':round(dbi,4) if dbi is not None else None,'cost':round(cost,5),'iterations':iterations,'normalization':{'min':mn.tolist(),'max':mx.tolist()},'variables':['setoran','murojaah','hafalan_tercapai','kehadiran'],'k':k}
