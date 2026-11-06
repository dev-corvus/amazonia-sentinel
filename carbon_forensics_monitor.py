# -*- coding: utf-8 -*-
"""Carbon Forensics: servidor local para tres HTMLs e SQLite existente."""
import gzip
import json
import math
import sqlite3
import threading
import webbrowser
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).resolve().parent
DB = BASE / 'carbon_forensics.sqlite'
PORT = 8000
LAYERS = {'historico', 'acumulado', 'hidrografia', 'residual', 'limite'}
YEARS = set(range(2020, 2026))
try:
    from shapely.geometry import shape, mapping, box
except ImportError:
    raise SystemExit('Instale: py -m pip install shapely')


def connect():
    con = sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=15000')
    con.execute('PRAGMA query_only=ON')
    return con


def get_stats(con):
    years = [dict(r) for r in con.execute('''
      SELECT year, COUNT(*) count, ROUND(SUM(COALESCE(area_ha,0)),2) area_ha
      FROM features WHERE layer='historico' AND year BETWEEN 2020 AND 2025
      GROUP BY year ORDER BY year''')]
    return {'years': years, 'layers': [dict(r) for r in con.execute('SELECT layer,count FROM imported')],
            'data_note': 'PRODES nao identifica sozinho corte seletivo, fogo, efeito de borda ou queda de arvores.'}


def get_map(con, layer, bbox, year, limit, detail):
    if layer not in LAYERS:
        raise ValueError('Camada desconhecida')
    if len(bbox) != 4 or not all(math.isfinite(x) for x in bbox):
        raise ValueError('Coordenadas invalidas')
    xmin, ymin, xmax, ymax = bbox
    # Leaflet pode apresentar longitudes fora do mundo ao afastar o zoom.
    xmin, xmax = max(-180, xmin), min(180, xmax)
    ymin, ymax = max(-85, ymin), min(85, ymax)
    if xmin >= xmax or ymin >= ymax:
        return {'type': 'FeatureCollection', 'features': [], 'truncated': False}
    if layer == 'historico' and year not in YEARS:
        raise ValueError('Escolha um ano entre 2020 e 2025')
    limit = max(25, min(500, limit))
    detail = max(0, min(0.03, detail))
    sql = '''SELECT f.id,f.year,f.area_ha,f.geom FROM spatial_idx s
       JOIN features f ON f.id=s.id
       WHERE f.layer=? AND s.maxx>=? AND s.minx<=? AND s.maxy>=? AND s.miny<=?'''
    args = [layer, xmin, xmax, ymin, ymax]
    if layer == 'historico':
        sql += ' AND f.year=?'
        args.append(year)
    sql += ' ORDER BY f.id LIMIT ?'
    args.append(limit + 1)
    rows = con.execute(sql, args).fetchall()
    region = box(xmin, ymin, xmax, ymax)
    features = []
    for r in rows[:limit]:
        try:
            geom = shape(json.loads(r['geom']))
            if not geom.intersects(region):
                continue
            geom = geom.intersection(region)
            if detail:
                geom = geom.simplify(detail, preserve_topology=True)
            if geom.is_empty:
                continue
            features.append({'type':'Feature', 'id':r['id'], 'geometry':mapping(geom),
                             'properties':{'id':r['id'], 'ano':r['year'], 'area_ha':r['area_ha'], 'camada':layer}})
        except Exception:
            continue
    return {'type':'FeatureCollection','features':features,'truncated':len(rows)>limit,'limit':limit}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if ' 200 ' not in (fmt % args):
            super().log_message(fmt, *args)

    def send_data(self, obj, code=200, content_type='application/json; charset=utf-8'):
        raw = obj.encode('utf-8') if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        compressed = 'gzip' in self.headers.get('Accept-Encoding', '') and len(raw) > 1024
        if compressed:
            raw = gzip.compress(raw, compresslevel=3)
        try:
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            if compressed:
                self.send_header('Content-Encoding', 'gzip')
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ('/', '/index.html', '/camadas_1.html', '/camadas_2.html'):
            name = 'index.html' if u.path == '/' else u.path[1:]
            return self.send_data((BASE / name).read_text(encoding='utf-8'), content_type='text/html; charset=utf-8')
        if u.path == '/favicon.ico':
            return self.send_data('', 204, 'text/plain')
        try:
            q = parse_qs(u.query)
            with connect() as con:
                if u.path == '/api/stats':
                    return self.send_data(get_stats(con))
                if u.path == '/api/feature':
                    fid = int(q.get('id', ['0'])[0])
                    r = con.execute('SELECT id,layer,year,area_ha,attrs FROM features WHERE id=?', (fid,)).fetchone()
                    return self.send_data(dict(r) | {'attributes':json.loads(r['attrs'])} if r else {'error':'Nao encontrado'}, 200 if r else 404)
                if u.path == '/api/map':
                    bbox = [float(v) for v in q.get('bbox',[''])[0].split(',')]
                    layer = q.get('layer',['historico'])[0]
                    year = int(q.get('year',['2025'])[0]) if layer == 'historico' else None
                    limit = int(q.get('limit',['250'])[0])
                    detail = float(q.get('detail',['0.0003'])[0])
                    return self.send_data(get_map(con,layer,bbox,year,limit,detail))
            return self.send_data({'error':'Rota nao encontrada'},404)
        except (ValueError, TypeError) as e:
            return self.send_data({'error':str(e)},400)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return
        except Exception as e:
            print('ERRO:',repr(e),flush=True)
            return self.send_data({'error':str(e)},500)


if __name__ == '__main__':
    if not DB.exists():
        raise SystemExit(f'Banco nao encontrado: {DB}\nCopie o carbon_forensics.sqlite existente para esta pasta.')
    for filename in ('index.html','camadas_1.html','camadas_2.html'):
        if not (BASE / filename).exists():
            raise SystemExit('Arquivo ausente: ' + filename)
    with connect() as con:
        con.execute('SELECT id FROM features LIMIT 1').fetchone()
    server = ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    print(f'Carbon Forensics pronto: http://127.0.0.1:{PORT}\nCtrl+C para encerrar',flush=True)
    threading.Timer(1, lambda:webbrowser.open(f'http://127.0.0.1:{PORT}')).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('Servidor encerrado')
    finally:
        server.server_close()
