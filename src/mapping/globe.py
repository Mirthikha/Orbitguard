"""Three.js Earth globe bound to a completed ORBITGUARD analysis run.

Coordinates originate from the workflow's WGS-84 SGP4 ground track. The
browser loads Three.js and NASA Blue Marble texture over the public internet;
a deterministic graticule and opaque ocean-colour sphere remain if texture
loading fails.
"""
from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import math

WGS84_A_M = 6_378_137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)
THREE_VERSION = "0.170.0"
THREE_MODULE_URL = f"https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/build/three.module.js"
THREE_ADDONS_URL = f"https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}/examples/jsm/"
NASA_TEXTURE_URL = (
    "https://assets.science.nasa.gov/content/dam/science/esd/eo/images/bmng/"
    "bmng-topography/january/world.topo.200401.3x5400x2700.jpg"
)
NASA_TEXTURE_ATTRIBUTION = "NASA Earth Observatory — Blue Marble Next Generation"


def geodetic_to_ecef_m(latitude_deg: float, longitude_deg: float) -> tuple[float, float, float]:
    """Convert WGS-84 geodetic coordinates at zero altitude to ECEF metres."""
    latitude, longitude = float(latitude_deg), float(longitude_deg)
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("Latitude must be finite and between -90 and 90 degrees.")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("Longitude must be finite and between -180 and 180 degrees.")
    lat, lon = math.radians(latitude), math.radians(longitude)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    n = WGS84_A_M / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
    return (n * cos_lat * math.cos(lon), n * cos_lat * math.sin(lon),
            n * (1 - WGS84_E2) * sin_lat)


def geodetic_to_three_unit(latitude_deg: float, longitude_deg: float) -> tuple[float, float, float]:
    """Map geodetic lat/lon to the unit sphere used by the Three.js mesh.

    Three.js Y is north. At lon=0 the texture-aligned position is +Z; positive
    east longitude rotates toward +X. The Earth mesh is rotated -90 degrees
    about Y to align the equirectangular NASA texture with that convention.
    """
    latitude, longitude = float(latitude_deg), float(longitude_deg)
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("Latitude must be finite and between -90 and 90 degrees.")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("Longitude must be finite and between -180 and 180 degrees.")
    lat, lon = math.radians(latitude), math.radians(longitude)
    c = math.cos(lat)
    return (math.sin(lon) * c, math.sin(lat), math.cos(lon) * c)


def _split_track(points: list[dict]) -> list[list[dict]]:
    """Retain valid run points while splitting propagation gaps and wraps."""
    segments: list[list[dict]] = []
    current: list[dict] = []
    previous_lon: float | None = None
    for point in points:
        try:
            lat, lon = float(point["latitude"]), float(point["longitude"])
            altitude, moment = float(point["altitude_km"]), point["time"]
            valid = (math.isfinite(lat) and -90 <= lat <= 90 and math.isfinite(lon)
                     and -180 <= lon <= 180 and math.isfinite(altitude)
                     and isinstance(moment, datetime) and moment.tzinfo is not None)
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            if current:
                segments.append(current)
                current = []
            previous_lon = None
            continue
        if current and (point.get("break_before") or
                        (previous_lon is not None and abs(lon - previous_lon) > 180)):
            segments.append(current)
            current = []
        x, y, z = geodetic_to_three_unit(lat, lon)
        current.append({
            "latitude": lat, "longitude": lon, "altitude_km": altitude,
            "time_utc": moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "three_xyz": [x, y, z],
        })
        previous_lon = lon
    if current:
        segments.append(current)
    return segments


def build_globe_payload(run: dict) -> dict:
    """Build globe data only from a complete, fingerprint-matched analysis run."""
    run_id = run.get("run_id")
    if not run_id or run.get("configuration_fingerprint") != run_id:
        raise ValueError("The globe requires a complete analysis run with a matching fingerprint.")
    segments = _split_track(run.get("points", []))
    if not segments:
        raise ValueError("The active analysis run has no valid positions for the globe.")
    return {"run_id": run_id, "object_name": str(run.get("name", "Selected object")),
            "catalog_id": str(run.get("catalog_id", "")), "segments": segments}


def create_three_globe_html(run: dict) -> str:
    """Create a responsive Three.js globe for the exact active analysis run."""
    payload = json.dumps(build_globe_payload(run), separators=(",", ":"), ensure_ascii=True)
    payload = (payload.replace("<", "\\u003c").replace(">", "\\u003e")
               .replace("&", "\\u0026").replace("\u2028", "\\u2028")
               .replace("\u2029", "\\u2029"))
    title = html.escape(f"{run.get('name', 'Selected object')} · SGP4 ground track")
    return f'''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
html,body,#globe{{width:100%;height:100%;min-height:580px;margin:0;overflow:hidden;background:#071827}}
#globe{{position:relative;border:1px solid #1c3549;border-radius:12px;overflow:hidden;color:#e7f1f7;font:13px system-ui,sans-serif}}
canvas{{display:block;width:100%;height:100%}}
#title,#status,#hover,#credit{{position:absolute;z-index:2;background:rgba(7,24,39,.91);border:1px solid #254257;border-radius:7px;padding:7px 10px;pointer-events:none}}
#title{{top:12px;left:14px;font-weight:650;max-width:70%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
#diagnostics{{position:absolute;z-index:3;top:12px;right:14px;width:min(390px,52%);max-height:calc(100% - 80px);overflow:auto;background:rgba(7,24,39,.94);border:1px solid #254257;border-radius:8px;padding:8px 10px;color:#b9cbd7;font-size:10px;line-height:1.4;pointer-events:none}}
.diagnostic-row{{padding:3px 0;border-bottom:1px solid rgba(75,105,128,.35);overflow-wrap:anywhere}}
.diagnostic-row:last-child{{border-bottom:0}}
.diagnostic-label{{color:#8ca8ba;font-weight:650}}
.diagnostic-value{{color:#d7e6ef}}
#hover{{display:none;left:14px;bottom:42px;max-width:min(360px,80%);font-size:12px;line-height:1.55;white-space:pre-line}}
#credit{{right:12px;bottom:8px;font-size:10px;color:#b9cbd7}}
#credit a{{color:#35e0d0;pointer-events:auto}}
#fallback{{position:absolute;z-index:1;inset:0;display:grid;place-items:center;background:#071827}}
.fallback-sphere{{position:relative;width:min(70vw,420px);aspect-ratio:1;border-radius:50%;background:radial-gradient(circle at 34% 27%,#42677f 0,#29475e 48%,#102b40 80%,#071827 100%);box-shadow:inset -24px -12px 48px #03101c,0 0 48px #0c4050}}
.fallback-sphere:before,.fallback-sphere:after{{content:"";position:absolute;left:50%;top:50%;width:min(70vw,420px);aspect-ratio:1;border:1px solid rgba(53,224,208,.32);border-radius:50%;transform:translate(-50%,-50%) scaleX(.35)}}
.fallback-sphere:after{{transform:translate(-50%,-50%) scaleX(.7);border-color:rgba(110,155,179,.35)}}
</style></head><body><div id="globe">
<div id="fallback"><div class="fallback-sphere" aria-label="Fallback blue Earth with longitude grid"></div></div>
<div id="title">{title}</div><div id="diagnostics" aria-live="polite" aria-label="Globe rendering diagnostics">
<div class="diagnostic-row" id="html-js-status"><span class="diagnostic-label">HTML / JavaScript:</span> <span class="diagnostic-value">HTML loaded; JavaScript module has not started.</span></div>
<div class="diagnostic-row" id="three-status"><span class="diagnostic-label">Three.js:</span> <span class="diagnostic-value">Module pending.</span></div>
<div class="diagnostic-row" id="renderer-status"><span class="diagnostic-label">WebGL renderer:</span> <span class="diagnostic-value">Pending.</span></div>
<div class="diagnostic-row" id="texture-status"><span class="diagnostic-label">Earth texture:</span> <span class="diagnostic-value">Pending.</span></div>
<div class="diagnostic-row" id="track-status"><span class="diagnostic-label">Track geometry:</span> <span class="diagnostic-value">Pending.</span></div>
<div class="diagnostic-row" id="exception-status"><span class="diagnostic-label">JavaScript exception:</span> <span class="diagnostic-value">None reported.</span></div>
</div>
<div id="hover"></div><div id="credit">Earth texture: <a href="https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography/" target="_blank" rel="noopener noreferrer">{NASA_TEXTURE_ATTRIBUTION}</a></div>
</div>
<script type="importmap">{{"imports":{{"three":"{THREE_MODULE_URL}","three/addons/":"{THREE_ADDONS_URL}"}}}}</script>
<script type="module">
const data={payload};
const fallback=document.getElementById('fallback');
const setDiagnostic=(id,message,warning=false)=>{{
  const row=document.getElementById(id);if(!row)return;
  const value=row.querySelector('.diagnostic-value');if(value)value.textContent=message;
  row.style.color=warning?'#F5B942':'#b9cbd7';
}};
const logError=(stage,error)=>console.error('ORBITGUARD Three.js '+stage,error&&error.name,error&&error.message,error&&error.stack||error);
let currentStage='module startup';
setDiagnostic('html-js-status','Initialized · active run '+data.run_id.slice(0,12));
setDiagnostic('three-status','Loading version '+{json.dumps(THREE_VERSION)}+' from jsDelivr…');
try {{
  currentStage='Three.js module import';
  const THREE=await import('three');
  const {{OrbitControls}}=await import('three/addons/controls/OrbitControls.js');
  setDiagnostic('three-status','Available · version '+(THREE.REVISION||'unknown')+'; OrbitControls loaded.');
  const host=document.getElementById('globe');
  currentStage='WebGL renderer creation';
  setDiagnostic('renderer-status','Creating WebGL renderer…');
  const renderer=new THREE.WebGLRenderer({{antialias:true,alpha:false}});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
  renderer.setSize(host.clientWidth,host.clientHeight);
  renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.domElement.setAttribute('aria-label','Interactive Three.js Earth showing the active SGP4 ground track');
  host.insertBefore(renderer.domElement,document.getElementById('title'));
  setDiagnostic('renderer-status','Created · canvas '+renderer.domElement.width+' × '+renderer.domElement.height+'.');
  currentStage='Earth scene setup';
  const scene=new THREE.Scene(); scene.background=new THREE.Color('#071827');
  const camera=new THREE.PerspectiveCamera(38,host.clientWidth/host.clientHeight,.1,100);
  const earthGroup=new THREE.Group(); scene.add(earthGroup);
  const earthGeometry=new THREE.SphereGeometry(1,96,64);
  const earthMaterial=new THREE.MeshBasicMaterial({{color:0x31546b}});
  const earth=new THREE.Mesh(earthGeometry,earthMaterial); earth.rotation.y=-Math.PI/2; earthGroup.add(earth);
  const gridMaterial=new THREE.LineBasicMaterial({{color:0x5c8296,transparent:true,opacity:.42}});
  const grid=new THREE.Group();
  function gridLine(coords){{const geometry=new THREE.BufferGeometry().setFromPoints(coords.map(v=>new THREE.Vector3(...v)));grid.add(new THREE.Line(geometry,gridMaterial));}}
  for(let latitude=-60;latitude<=60;latitude+=30){{const points=[];for(let longitude=-180;longitude<=180;longitude+=4)points.push([...geo(latitude,longitude,1.002)]);gridLine(points);}}
  for(let longitude=-180;longitude<180;longitude+=30){{const points=[];for(let latitude=-88;latitude<=88;latitude+=4)points.push([...geo(latitude,longitude,1.002)]);gridLine(points);}}
  earthGroup.add(grid);
  const controls=new OrbitControls(camera,renderer.domElement); controls.enableDamping=true;controls.dampingFactor=.07;controls.minDistance=1.25;controls.maxDistance=8;controls.enablePan=false;
  const all=data.segments.flat();
  currentStage='track geometry creation';
  setDiagnostic('track-status','Building geometry from '+all.length+' run-bound positions…');
  if(!all.length||all.some(p=>!Array.isArray(p.three_xyz)||p.three_xyz.length!==3||!p.three_xyz.every(Number.isFinite)))
    throw new Error('Track coordinates are empty or invalid.');
  const mean=new THREE.Vector3();for(const p of all)mean.add(new THREE.Vector3(...p.three_xyz));
  if(mean.lengthSq()>1e-8)camera.position.copy(mean.normalize().multiplyScalar(3.25));else camera.position.set(2.4,1.35,2.4);
  controls.target.set(0,0,0);controls.update();
  const trackMaterial=new THREE.LineBasicMaterial({{color:0x35e0d0,transparent:true,opacity:.98}});
  for(const segment of data.segments){{
    const positions=segment.map(p=>{{const v=geo(p.latitude,p.longitude,1.009);return new THREE.Vector3(...v);}});
    if(positions.length>1)earthGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(positions),trackMaterial));
  }}
  const markers=[];
  function addMarker(point,color,label){{const mesh=new THREE.Mesh(new THREE.SphereGeometry(.018,16,12),new THREE.MeshBasicMaterial({{color}}));mesh.position.set(...geo(point.latitude,point.longitude,1.025));mesh.userData={{point,label}};earthGroup.add(mesh);markers.push(mesh);}}
  const positionGeometry=new THREE.SphereGeometry(.007,8,6);
  const positionMaterial=new THREE.MeshBasicMaterial({{color:0x35e0d0}});
  for(const segment of data.segments)for(const point of segment){{
    if(point===all[0]||point===all[all.length-1])continue;
    const mesh=new THREE.Mesh(positionGeometry,positionMaterial);
    mesh.position.set(...geo(point.latitude,point.longitude,1.018));
    mesh.userData={{point,label:'SGP4 POSITION'}};earthGroup.add(mesh);markers.push(mesh);
  }}
  const first=data.segments[0][0],last=data.segments[data.segments.length-1].at(-1);
  addMarker(first,0xf8fbff,'START');addMarker(last,0xf5b942,'END');
  setDiagnostic('track-status','Created · '+all.length+' positions across '+data.segments.length+' gap/wrap-safe segment(s) · run '+data.run_id.slice(0,12)+'.');
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2(),hover=document.getElementById('hover');
  renderer.domElement.addEventListener('pointermove',event=>{{const rect=renderer.domElement.getBoundingClientRect();pointer.set(((event.clientX-rect.left)/rect.width)*2-1,-((event.clientY-rect.top)/rect.height)*2+1);raycaster.setFromCamera(pointer,camera);const hit=raycaster.intersectObjects(markers)[0];if(!hit){{hover.style.display='none';return;}}const {{point,label}}=hit.object.userData;hover.textContent=label+' · '+data.object_name+' (NORAD '+data.catalog_id+')\\nUTC: '+point.time_utc+'\\nLatitude: '+point.latitude.toFixed(5)+'° · Longitude: '+point.longitude.toFixed(5)+'°\\nSGP4 altitude: '+point.altitude_km.toFixed(3)+' km';hover.style.display='block';}});
  let active=true;function resize(){{if(!active)return;const w=host.clientWidth,h=host.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}}
  new ResizeObserver(resize).observe(host);
  function render(){{if(!active)return;requestAnimationFrame(render);controls.update();renderer.render(scene,camera);}}
  render();fallback.style.display='none';
  setDiagnostic('html-js-status','Initialized · scene rendered for run '+data.run_id.slice(0,12)+'.');
  currentStage='NASA Earth texture request';
  setDiagnostic('texture-status','Loading NASA Blue Marble texture…');
  const loader=new THREE.TextureLoader();loader.setCrossOrigin('anonymous');
  loader.load('{NASA_TEXTURE_URL}',texture=>{{texture.colorSpace=THREE.SRGBColorSpace;earth.material.dispose();earth.material=new THREE.MeshBasicMaterial({{map:texture}});setDiagnostic('texture-status','Loaded · NASA Earth Observatory Blue Marble.');}},undefined,error=>{{logError('Earth texture load failed',error);setDiagnostic('texture-status','Failed · fallback Earth and graticule remain visible (network/CORS).',true);}});
  window.addEventListener('beforeunload',()=>{{active=false;controls.dispose();renderer.dispose();}});
}} catch(error) {{
  logError(currentStage,error);
  const detail=(error&&error.name?error.name+': ':'')+(error&&error.message?error.message:String(error));
  setDiagnostic('exception-status',currentStage+' — '+detail,true);
  if(currentStage==='Three.js module import')setDiagnostic('three-status','Failed · '+detail,true);
  if(currentStage==='WebGL renderer creation')setDiagnostic('renderer-status','Failed · '+detail,true);
  if(currentStage==='NASA Earth texture request')setDiagnostic('texture-status','Failed · '+detail,true);
  if(currentStage==='track geometry creation')setDiagnostic('track-status','Failed · '+detail,true);
  setDiagnostic('html-js-status','JavaScript started; initialization stopped at '+currentStage+'.',true);
}}
function geo(latitude,longitude,radius){{const lat=latitude*Math.PI/180,lon=longitude*Math.PI/180,c=Math.cos(lat);return [Math.sin(lon)*c*radius,Math.sin(lat)*radius,Math.cos(lon)*c*radius];}}
</script></body></html>'''
