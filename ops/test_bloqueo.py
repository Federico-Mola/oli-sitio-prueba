"""Pruebas Linux del bloqueo real, sin catálogo, red ni servicios de producción."""
import fcntl
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path
from oli_operacion import tomar_bloqueo

def ocupar(path,ready,seconds):
    with open(path,'a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        ready.set()
        time.sleep(seconds)

class BloqueoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'operacion.lock'
    def tearDown(self):
        self.temp.cleanup()
    def competir(self,modo,espera,duracion):
        ready=multiprocessing.Event()
        process=multiprocessing.Process(target=ocupar,args=(self.path,ready,duracion))
        process.start()
        try:
            self.assertTrue(ready.wait(5))
            with self.path.open('a') as lock:
                start=time.monotonic()
                result=tomar_bloqueo(lock,modo,espera)
                return result,time.monotonic()-start
        finally:
            process.join(5)
            if process.is_alive():process.terminate();process.join()
    def test_respaldo_espera_y_adquiere(self):
        result,elapsed=self.competir('backup',3,0.6)
        self.assertTrue(result)
        self.assertGreaterEqual(elapsed,0.4)
    def test_monitor_omite_sin_fallar(self):
        result,elapsed=self.competir('monitor',3,0.6)
        self.assertFalse(result)
        self.assertLess(elapsed,0.5)
    def test_respaldo_tiene_espera_acotada(self):
        with self.assertRaises(TimeoutError):self.competir('backup',0.1,0.6)
    def test_bloqueo_libre(self):
        with self.path.open('a') as lock:self.assertTrue(tomar_bloqueo(lock,'backup'))

if __name__=='__main__':unittest.main(verbosity=2)
