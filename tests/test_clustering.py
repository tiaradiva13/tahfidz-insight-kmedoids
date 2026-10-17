import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from clustering import cluster

class ClusteringTest(unittest.TestCase):
    def setUp(self):
        self.data=[{'id':i,'setoran':v,'murojaah':v*2+1,'hafalan_tercapai':v/2,'kehadiran':65+v/3} for i,v in enumerate([2,3,4,10,11,12,22,23,24],1)]
    def test_groups_and_metrics(self):
        x=cluster(self.data,3)
        self.assertEqual(len(x['labels']),9)
        self.assertEqual(sum(a['jumlah'] for a in x['groups']),9)
        self.assertIsNotNone(x['silhouette']);self.assertIsNotNone(x['dbi'])
        self.assertEqual(x['variables'],['setoran','murojaah','hafalan_tercapai','kehadiran'])
    def test_reproducible(self):self.assertEqual(cluster(self.data,3),cluster(self.data,3))
    def test_invalid_k(self):
        with self.assertRaises(ValueError):cluster(self.data,10)
    def test_insufficient_variation(self):
        with self.assertRaises(ValueError):cluster([dict(v,setoran=1,murojaah=1,hafalan_tercapai=1,kehadiran=90) for v in self.data],3)
if __name__=='__main__':unittest.main()
