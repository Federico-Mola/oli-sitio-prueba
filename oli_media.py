"""Archivos propios de Oli: validar, normalizar y guardar versiones inmutables."""
import io
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

MAX_ARCHIVO = 100 * 1024 * 1024
MAX_FOTO = 50 * 1024 * 1024
MAX_VIDEO_SEGUNDOS = 180


class MediaError(Exception):
    pass


def tipo_archivo(path):
    with open(path, 'rb') as f:
        head = f.read(32)
    if head[4:8] == b'ftyp':
        return 'mov'
    if head[:4] == b'\x1aE\xdf\xa3':
        return 'matroska'
    return 'imagen'


def imagen(path):
    from PIL import Image, ImageOps
    try:
        with Image.open(path) as source:
            if source.format not in ('JPEG','PNG','WEBP') or source.width * source.height > 40_000_000:
                raise MediaError('Usá una foto JPG, PNG o WebP de hasta 40 megapíxeles.')
            source.load()
            im = ImageOps.exif_transpose(source).convert('RGB')
        return im
    except MediaError:
        raise
    except Exception:
        raise MediaError('No pude abrir esa foto. Probá con JPG, PNG o WebP.') from None


def video_info(path):
    formato = tipo_archivo(path)
    if formato not in ('mov','matroska'):
        raise MediaError('Usá un video MP4, MOV o WebM.')
    try:
        r = subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-f',formato,
            '-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(path)],
            capture_output=True,timeout=20,env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'C'})
        if r.returncode:
            raise ValueError()
        info = json.loads(r.stdout)
        duration = float(info['format']['duration'])
        stream = next(s for s in info['streams'] if s.get('codec_type') == 'video')
        if not 0 < duration <= MAX_VIDEO_SEGUNDOS or max(stream['width'],stream['height']) > 8192:
            raise MediaError('El video debe durar hasta 3 minutos y tener resolución de hasta 8K.')
        return formato, duration
    except MediaError:
        raise
    except Exception:
        raise MediaError('No pude comprobar el video. Probá con otro MP4, MOV o WebM.') from None


def validar_archivo(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_ARCHIVO:
        raise MediaError('El archivo debe pesar hasta 100 MB.')
    if tipo_archivo(path) == 'imagen':
        if path.stat().st_size > MAX_FOTO:
            raise MediaError('Cada foto debe pesar hasta 50 MB.')
        im = imagen(path); im.close()
        return 'foto'
    video_info(path)
    return 'video'


def materializar(api, codigo, fotos, portada=0, video=None):
    """No modifica archivos que una versión pública anterior pueda estar sirviendo."""
    if not re.fullmatch(r'(ACC|COR|VEL|COL|NAV|PAS)-\d{4,}',codigo):
        raise MediaError('Código inválido.')
    if not 1 <= len(fotos) <= 10 or not 0 <= portada < len(fotos):
        raise MediaError('Guardá entre una y diez fotos y elegí una portada válida.')
    carpeta = api.MEDIA / 'modelos' / codigo / ('v-' + uuid.uuid4().hex[:16])
    carpeta.mkdir(parents=True,exist_ok=False)
    def source(entry):
        public=entry.get('publica','')
        if re.fullmatch(r'/img/[a-zA-Z0-9_-]+\.webp',public):
            from oli_publicacion import SITE
            path=SITE/public.lstrip('/')
            if path.is_file():return path
        rel = entry.get('archivo') or entry.get('publica','').lstrip('/')
        path = (api.DATA / rel).resolve()
        if not path.is_relative_to(api.MEDIA.resolve()) or not path.is_file():
            raise MediaError('Falta un archivo. Reabrí Fotos y volvé a cargarlo.')
        return path
    ordered = [fotos[portada]] + [f for i,f in enumerate(fotos) if i != portada]
    rutas = []; tg=[]
    for i,entry in enumerate(ordered,1):
        im = imagen(source(entry)); im.thumbnail((1200,1200))
        path=carpeta/f'{i}.webp';im.save(path,'WEBP',quality=82)
        if i==1:im.save(carpeta/'og.jpg','JPEG',quality=85)
        im.thumbnail((600,600));im.save(carpeta/f'{i}-600.webp','WEBP',quality=80);im.close()
        rutas.append('/'+path.relative_to(api.DATA).as_posix());tg.append(entry.get('file_id'))
    result={'fotos':rutas,'fotos_tg':tg,'imagen_social':'/'+(carpeta/'og.jpg').relative_to(api.DATA).as_posix(),'video':None}
    if video:
        src=source(video);formato,duration=video_info(src);dest=carpeta/'video.mp4'
        try:
            r=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y',
                '-protocol_whitelist','file,pipe','-f',formato,'-i',str(src),'-map','0:v:0','-map','0:a:0?',
                '-vf',"scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                '-c:v','libx264','-preset','veryfast','-crf','25','-threads','1','-pix_fmt','yuv420p',
                '-c:a','aac','-b:a','96k','-map_metadata','-1','-map_chapters','-1','-movflags','+faststart','-fs',str(50*1024*1024),str(dest)],
                capture_output=True,timeout=120,env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'C'})
            if r.returncode or not dest.is_file():raise ValueError()
            _, out_duration=video_info(dest)
            if out_duration < duration-2:raise ValueError()
        except Exception:
            raise MediaError('No pude preparar el video para la web. Conservé el modelo anterior.') from None
        result['video']='/'+dest.relative_to(api.DATA).as_posix()
    return result
