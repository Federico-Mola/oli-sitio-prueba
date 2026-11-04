"""Regresión del circuito de carga. Ejecutar en un contenedor sin red ni datos reales."""
import sys,unittest,json,importlib,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
suite=unittest.TestSuite()
for module in ['test_publicacion','test_gestion','test_recepcion']:
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module))
for module,name in [('test_album','AlbumTests'),('test_album','ContinuidadFotosTests'),('test_solidez','SolidezTests')]:
    cls=getattr(importlib.import_module(module),name)
    for method in sorted(cls.__dict__):
        if method.startswith('test_'):suite.addTest(cls(method))
result=unittest.TextTestRunner(verbosity=2).run(suite)
report={'casos':result.testsRun,'omitidos':len(result.skipped),'errores':len(result.errors),'fallos':len(result.failures),'correcto':result.wasSuccessful()}
pathlib.Path('SOLIDEZ-PRUEBAS.json').write_text(json.dumps(report,indent=2))
raise SystemExit(0 if result.wasSuccessful() else 1)
