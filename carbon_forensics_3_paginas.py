# -*- coding: utf-8 -*-
"""Carbon Forensics Web: servidor local e banco espacial SQLite.
Instalar: py -m pip install pyshp shapely pyproj
Executar: py carbon_forensics_3_paginas.py
"""
import json, math, os, sqlite3, threading, time, webbrowser, gzip
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from collections import defaultdict

try:
    import shapefile
    from shapely.geometry import shape, mapping, box
    from shapely.ops import transform as shape_transform
    from shapely.prepared import prep
    from pyproj import CRS, Transformer, Geod
except ImportError as e:
    raise SystemExit('Dependencia ausente: py -m pip install pyshp shapely pyproj\n' + str(e))

BASE = Path(__file__).resolve().parent
DATA = BASE / 'dados_reais'
DB = BASE / 'carbon_forensics.sqlite'
PORT = 8000
YEARS_ALLOWED = tuple(range(2020, 2026))
DEFAULT_YEAR = 2025
SOURCES = {
    'limite': DATA / 'amazonia_legal' / 'Limites_Amazonia_Legal_2024.shp',
    'historico': DATA / 'prodes' / 'yearly_deforestation_amazonia_legal_v20261016.shp',
    'acumulado': DATA / 'prodes' / 'accumulated_deforestation_2007_amazonia_legal_v20261016.shp',
    'hidrografia': DATA / 'prodes' / 'hydrography_amazonia_legal_v20261016.shp',
    'residual': DATA / 'prodes' / 'residual_2026_pri_amazonia_legal_v20261015.shp',
}
GEOD = Geod(ellps='WGS84')
WRITE_LOCK = threading.Lock()

def connection():
    con = sqlite3.connect(DB, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=60000')
    return con

def initialize(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS features (
      id INTEGER PRIMARY KEY, layer TEXT NOT NULL, year INTEGER,
      area_ha REAL, attrs TEXT NOT NULL, geom TEXT NOT NULL
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS spatial_idx USING rtree(id,minx,maxx,miny,maxy);
    CREATE TABLE IF NOT EXISTS imported(layer TEXT PRIMARY KEY, source TEXT, count INTEGER, finished TEXT);
    CREATE INDEX IF NOT EXISTS features_layer_year ON features(layer,year);
    ''')
    con.commit()

def clean_value(v):
    if isinstance(v, bytes):
        return v.decode('utf-8', 'replace')
    if v is None or isinstance(v, (str, int, float, bool)):
        if isinstance(v, float) and not math.isfinite(v): return None
        return v
    return str(v)

def infer_year(attrs):
    lower = {str(k).lower(): v for k,v in attrs.items()}
    for key in ('year','ano','year_def','def_year','year_deforestation','ano_desmatamento','image_year','main_class'):
        if key not in lower: continue
        try:
            year = int(float(str(lower[key]).strip()))
            if 1980 <= year <= 2100: return year
        except (ValueError, TypeError): pass
    return None

def import_one(con, layer, path):
    if not path.exists():
        print('AVISO: shapefile ausente:', path)
        return
    row = con.execute('SELECT source FROM imported WHERE layer=?',(layer,)).fetchone()
    fingerprint = str(path.resolve()) + ':' + str(path.stat().st_size) + ':' + str(path.stat().st_mtime_ns)
    if row and row['source'] == fingerprint:
        print('OK, camada ja importada:', layer)
        return
    print('Importando', layer, '— pode levar alguns minutos... ', flush=True)
    con.execute('DELETE FROM spatial_idx WHERE id IN (SELECT id FROM features WHERE layer=?)',(layer,))
    con.execute('DELETE FROM features WHERE layer=?',(layer,))
    con.execute('DELETE FROM imported WHERE layer=?',(layer,))
    con.commit()
    reader = shapefile.Reader(str(path), encoding='utf-8', encodingErrors='replace')
    names = [f[0] for f in reader.fields[1:]]
    print('Campos de', layer, ':', ', '.join(names), flush=True)
    prj = path.with_suffix('.prj')
    if prj.exists():
        crs = CRS.from_wkt(prj.read_text(encoding='utf-8-sig', errors='replace'))
    else:
        raise RuntimeError(f'Arquivo .prj ausente: {prj}. Nao vou presumir o sistema de coordenadas.')
    transformer = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
    count = 0
    for rec in reader.iterShapeRecords():
        try:
            geom = shape(rec.shape.__geo_interface__)
            if geom.is_empty: continue
            if crs.to_epsg() != 4326:
                geom = shape_transform(transformer.transform, geom)
            if geom.is_empty: continue
            bounds = geom.bounds
            if not all(math.isfinite(x) for x in bounds): continue
            attrs = {k:clean_value(v) for k,v in zip(names, rec.record)}
            year = infer_year(attrs) if layer == 'historico' else None
            area_ha = None
            if geom.geom_type in ('Polygon','MultiPolygon'):
                try: area_ha = abs(GEOD.geometry_area_perimeter(geom)[0])/10000
                except Exception: pass
            cur = con.execute('INSERT INTO features(layer,year,area_ha,attrs,geom) VALUES(?,?,?,?,?)',
                (layer,year,area_ha,json.dumps(attrs,ensure_ascii=False),json.dumps(mapping(geom),separators=(',',':'))))
            con.execute('INSERT INTO spatial_idx VALUES(?,?,?,?,?)',(cur.lastrowid,bounds[0],bounds[2],bounds[1],bounds[3]))
            count += 1
            if count % 1000 == 0:
                con.commit()
                print(f'  {layer}: {count:,} registros', end='\r', flush=True)
        except Exception as e:
            if count < 10: print('Registro ignorado:',e)
    con.execute('INSERT INTO imported VALUES(?,?,?,datetime("now"))',(layer,fingerprint,count))
    con.commit()
    print(f'\nConcluido: {layer}: {count:,} feicoes', flush=True)

def prepare_db():
    con = connection()
    initialize(con)
    for layer,path in SOURCES.items(): import_one(con,layer,path)
    con.close()

def stats(con):
    layers = [dict(r) for r in con.execute('SELECT layer,count FROM imported ORDER BY layer')]
    years = [dict(r) for r in con.execute('''SELECT year,COUNT(*) AS count,ROUND(SUM(COALESCE(area_ha,0)),2) AS area_ha
        FROM features WHERE layer='historico' AND year BETWEEN 2020 AND 2025 GROUP BY year ORDER BY year''')]
    missing = con.execute("SELECT COUNT(*) FROM features WHERE layer='historico' AND year IS NULL").fetchone()[0]
    return {'layers':layers,'years':years,'without_year':missing}

def get_features(con, layer, bbox, year, limit, detail):
    if layer not in SOURCES: raise ValueError('Camada invalida')
    xmin,ymin,xmax,ymax = bbox
    if not all(math.isfinite(v) for v in bbox) or xmin >= xmax or ymin >= ymax:
        raise ValueError('bbox invalida')
    xmin, xmax = max(-180.0, xmin), min(180.0, xmax)
    ymin, ymax = max(-85.0, ymin), min(85.0, ymax)
    if xmin >= xmax or ymin >= ymax:
        return {'type':'FeatureCollection','features':[],'truncated':False,'limit':limit}
    sql = '''SELECT f.id,f.year,f.area_ha,f.geom FROM spatial_idx s
        JOIN features f ON f.id=s.id WHERE f.layer=? AND s.maxx>=? AND s.minx<=? AND s.maxy>=? AND s.miny<=?'''
    params = [layer,xmin,xmax,ymin,ymax]
    if layer == 'historico':
        if year is None or year not in YEARS_ALLOWED:
            raise ValueError('Selecione um ano entre 2020 e 2025')
        sql += ' AND f.year=?'; params.append(year)
    sql += ' ORDER BY f.id LIMIT ?'; params.append(limit+1)
    rows = con.execute(sql,params).fetchall()
    truncated = len(rows)>limit
    features = []
    # A geometria integral fica preservada no SQLite. Simplificacao apenas no envio para o navegador.
    clipper = box(xmin,ymin,xmax,ymax)
    for r in rows[:limit]:
        try:
            geom = shape(json.loads(r['geom']))
            if not geom.intersects(clipper): continue
            if detail > 0:
                geom = geom.simplify(detail,preserve_topology=True)
            geom = geom.intersection(clipper)
            if geom.is_empty: continue
            features.append({'type':'Feature','id':r['id'],'geometry':mapping(geom),
                'properties':{'id':r['id'],'ano':r['year'],'area_ha':r['area_ha']}})
        except Exception: continue
    return {'type':'FeatureCollection','features':features,'truncated':truncated,'limit':limit}

class Handler(BaseHTTPRequestHandler):
    def respond(self, data, status=200, content_type='application/json; charset=utf-8'):
        raw = data.encode('utf-8') if isinstance(data,str) else json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        if 'gzip' in self.headers.get('Accept-Encoding','') and len(raw)>1024:
            raw=gzip.compress(raw,compresslevel=3)
            self.send_header('Content-Encoding','gzip')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    def do_GET(self):
        url=urlparse(self.path);q=parse_qs(url.query)
        if url.path in ('/', '/index.html', '/mapa.html', '/dashboard.html'):
            name = 'index.html' if url.path == '/' else url.path.lstrip('/')
            return self.respond((BASE / name).read_text(encoding='utf-8'), content_type='text/html; charset=utf-8')
        try:
            with connection() as con:
                if url.path=='/api/stats':return self.respond(stats(con))
                if url.path=='/api/feature':
                    fid=int(q.get('id',['0'])[0]);r=con.execute('SELECT id,layer,year,area_ha,attrs FROM features WHERE id=?',(fid,)).fetchone()
                    if not r:return self.respond({'error':'Registro nao encontrado'},404)
                    return self.respond({'id':r['id'],'layer':r['layer'],'year':r['year'],'area_ha':r['area_ha'],'attributes':json.loads(r['attrs'])})
                if url.path=='/api/map':
                    layer=q.get('layer',['historico'])[0]
                    bbox=[float(x) for x in q.get('bbox',[''])[0].split(',')]
                    if len(bbox)!=4:raise ValueError('bbox deve ter quatro coordenadas')
                    year=int(q['year'][0]) if 'year' in q and q['year'][0] else (DEFAULT_YEAR if layer=='historico' else None)
                    limit=min(1000,max(10,int(q.get('limit',['1000'])[0])))
                    detail=max(0,min(1,float(q.get('detail',['0.0001'])[0])))
                    return self.respond(get_features(con,layer,bbox,year,limit,detail))
            return self.respond({'error':'Endereco nao encontrado'},404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except (ValueError,TypeError) as e:
            try: return self.respond({'error':str(e)},400)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): return
        except Exception as e:
            print('ERRO:',repr(e),flush=True)
            try: return self.respond({'error':str(e)},500)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): return

if __name__=='__main__':
    print('CARBON FORENSICS WEB — primeira execucao pode demorar.\n',flush=True)
    prepare_db()
    address=f'http://127.0.0.1:{PORT}'
    print('\nPRONTO! Abra:',address,'\nPara encerrar: Ctrl+C\n',flush=True)
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    threading.Timer(1.0,lambda:webbrowser.open(address)).start()
    try:server.serve_forever()
    except KeyboardInterrupt:print('\nServidor encerrado.')
    finally:server.server_close()
