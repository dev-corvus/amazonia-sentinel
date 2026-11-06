# -*- coding: utf-8 -*-
"""Carbon Forensics Web: servidor local e banco espacial SQLite.
Instalar: py -m pip install pyshp shapely pyproj
Executar: py carbon_forensics_web.py
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

HTML = r'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Carbon Forensics | Amazônia Legal</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
*{box-sizing:border-box}body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#0b1220;color:#e2e8f0}
header{height:60px;display:flex;align-items:center;padding:0 22px;background:#0f172a;border-bottom:1px solid #334155}
header b{font-size:21px;letter-spacing:1px}header small{margin-left:16px;color:#94a3b8}
main{display:grid;grid-template-columns:minmax(0,1fr) 350px;height:calc(100vh - 60px)}#map{height:100%;width:100%;background:#cad4dc}
aside{overflow:auto;padding:18px;background:#101c2d;border-left:1px solid #334155}
h3{margin:8px 0 12px;font-size:15px;color:#93c5fd}label{display:block;margin:8px 0}
select,button{width:100%;padding:10px;border-radius:7px;background:#1e293b;color:white;border:1px solid #475569}
button{cursor:pointer;background:#2563eb;border:0;margin-top:9px}button:hover{background:#1d4ed8}
.card{background:#17263b;border:1px solid #293c53;padding:12px;border-radius:10px;margin:12px 0}
small,.muted{color:#94a3b8}#details{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;max-height:260px;overflow:auto}
#chart{width:100%;height:170px}#status{font-size:12px;color:#fde68a;line-height:1.5}
.leaflet-container{background:#dbe3e9}@media(max-width:850px){main{display:block;height:auto}#map{height:60vh}aside{height:auto}}
</style></head><body>
<header><b>CARBON FORENSICS</b><small>Amazônia Legal · PRODES / IBGE</small></header>
<main><div id="map"></div><aside>
<h3>Filtros</h3><label>Ano do desmatamento <select id="year"></select></label>
<h3>Camadas</h3><label><input type="checkbox" data-layer="limite" checked> Limite IBGE — azul</label>
<label><input type="checkbox" data-layer="historico" checked> PRODES histórico — vermelho</label>
<label><input type="checkbox" data-layer="hidrografia"> Hidrografia — azul-claro</label>
<label><input type="checkbox" data-layer="acumulado"> Acumulado até 2007 — amarelo</label>
<label><input type="checkbox" data-layer="residual"> Residual preliminar 2026 — roxo</label>
<button id="reload">Atualizar área visível</button>
<div class="card"><h3>Histórico anual (base completa)</h3><canvas id="chart"></canvas><div class="muted" style="font-size:11px">Área calculada a partir das geometrias, em hectares; pode diferir de métricas oficiais publicadas.</div></div>
<div class="card"><h3>Resumo</h3><div id="summary">Carregando...</div></div>
<div class="card"><h3>Informações do polígono</h3><div id="details">Passe o mouse sobre uma área ou clique para ver todos os atributos.</div></div>
<div class="card"><h3>Estado do mapa</h3><div id="status">Iniciando...</div></div>
<div class="muted" style="font-size:11px">O desmatamento mapeado não demonstra, por si só, ilegalidade ou fraude de carbono. O residual 2026 é preliminar.</div>
</aside></main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
if(!window.L){document.getElementById('status').textContent='A biblioteca Leaflet não carregou. Verifique internet ou bloqueio de unpkg.com.';throw new Error('Leaflet indisponível');}
const map=L.map('map',{preferCanvas:false,minZoom:3,maxBounds:[[-22,-84],[12,-34]],maxBoundsViscosity:0.8}).setView([-5.3,-60],5);
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:18,attribution:'Esri World Imagery'}).addTo(map);
const colors={limite:'#00bfff',historico:'#ef4444',hidrografia:'#38bdf8',acumulado:'#facc15',residual:'#e879f9'};
const layers={};let controller=null,sequence=0;const svgRenderer=L.svg({padding:0.25});
for(const key of Object.keys(colors))layers[key]=L.geoJSON(null,{renderer:svgRenderer,interactive:true,style:()=>({color:colors[key],weight:key==='limite'?3:1,fillOpacity:key==='limite'?0:.38,opacity:.9}),
 onEachFeature:(feature,layer)=>{layer.on('mouseover',()=>{showFeature(feature,false);layer.setStyle({weight:3,fillOpacity:0.65});});layer.on('mouseout',()=>layers[key].resetStyle(layer));layer.on('click',()=>showFeature(feature,true));}}).addTo(map);
const status=document.getElementById('status');const year=document.getElementById('year');
function enabled(key){return document.querySelector('[data-layer="'+key+'"]').checked}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function showFeature(feature,full){const p=feature.properties;let lines='ID: '+p.id+'\nAno: '+(p.ano??'não informado')+'\nÁrea: '+(p.area_ha==null?'não calculada':Number(p.area_ha).toLocaleString('pt-BR',{maximumFractionDigits:2})+' ha');
if(full){try{const r=await fetch('/api/feature?id='+encodeURIComponent(p.id));const d=await r.json();lines+='\n\nAtributos originais:\n'+JSON.stringify(d.attributes,null,2);}catch(e){lines+='\nErro ao carregar atributos: '+e.message;}}
document.getElementById('details').textContent=lines;}
async function update(){const seq=++sequence;if(controller)controller.abort();controller=new AbortController();const b=map.getBounds();const bbox=[b.getWest(),b.getSouth(),b.getEast(),b.getNorth()].join(',');let messages=[];
for(const key of Object.keys(layers)){
 if(!enabled(key)){layers[key].clearLayers();map.removeLayer(layers[key]);continue;}
 if(!map.hasLayer(layers[key]))layers[key].addTo(map);
 try{const params=new URLSearchParams({layer:key,bbox,limit:key==='historico'?'450':'120',detail:String(Math.max(0.00003,1.2/map.getZoom()**3))});if(key==='historico')params.set('year',year.value||'2025');
 const response=await fetch('/api/map?'+params,{signal:controller.signal});if(!response.ok)throw new Error(await response.text());const result=await response.json();if(seq!==sequence)return;
 layers[key].clearLayers();layers[key].addData(result);messages.push(key+': '+result.features.length+(result.truncated?' (limite atingido; aproxime o zoom)':''));
 }catch(e){if(e.name==='AbortError')return;messages.push(key+': erro '+e.message);}
}
status.textContent=messages.join('\n')+'\nOs totais históricos são calculados sobre a base inteira.';}
let pending;map.on('moveend',()=>{clearTimeout(pending);pending=setTimeout(update,550)});
document.querySelectorAll('[data-layer]').forEach(c=>c.addEventListener('change',update));year.addEventListener('change',update);document.getElementById('reload').addEventListener('click',update);
async function init(){try{const response=await fetch('/api/stats');if(!response.ok)throw new Error(await response.text());const data=await response.json();for(let y=2025;y>=2020;y--){const o=document.createElement('option');o.value=y;o.textContent=y;year.appendChild(o)}year.value='2025';
let total=data.years.reduce((a,b)=>a+b.count,0),area=data.years.reduce((a,b)=>a+b.area_ha,0);
document.getElementById('summary').textContent='Polígonos com ano: '+total.toLocaleString('pt-BR')+'\nÁrea histórica calculada: '+Math.round(area).toLocaleString('pt-BR')+' ha\nRegistros sem ano: '+data.without_year.toLocaleString('pt-BR')+'\nCamadas: '+data.layers.map(x=>x.layer+' ('+x.count.toLocaleString('pt-BR')+')').join(', ');
document.getElementById('summary').style.whiteSpace='pre-wrap';drawChart(data.years);update();}catch(e){status.textContent='Falha ao consultar o servidor: '+e.message;}}
function drawChart(years){const canvas=document.getElementById('chart'),ctx=canvas.getContext('2d');const dpr=window.devicePixelRatio||1;canvas.width=canvas.clientWidth*dpr;canvas.height=170*dpr;ctx.scale(dpr,dpr);const w=canvas.clientWidth,h=170;ctx.clearRect(0,0,w,h);if(!years.length)return;const max=Math.max(1,...years.map(x=>x.area_ha)),bar=w/years.length;
ctx.fillStyle='#38bdf8';years.forEach((r,i)=>{const hh=(h-40)*r.area_ha/max;ctx.fillRect(i*bar+2,h-25-hh,Math.max(2,bar-4),hh)});ctx.fillStyle='#cbd5e1';ctx.font='11px Segoe UI';ctx.fillText(years[0].year,3,h-7);ctx.fillText(years[years.length-1].year,w-40,h-7);}
init();
</script></body></html>'''

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
        if url.path in ('/','/index.html'):
            return self.respond(HTML,content_type='text/html; charset=utf-8')
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
