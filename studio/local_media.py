"""Local media types and bounded HTTP byte ranges; no remote downloads."""
import mimetypes
import re


def mime(name, raw=b''):
    from .avatars import image_kind
    image=image_kind(raw)
    if image:return image
    ext=str(name).lower().rsplit('.',1)[-1]
    return {'mp4':'video/mp4','webm':'video/webm','mp3':'audio/mpeg','ogg':'audio/ogg','oga':'audio/ogg',
            'm4a':'audio/mp4','aac':'audio/aac','wav':'audio/wav','mid':'audio/midi','midi':'audio/midi'}.get(ext) or 'application/octet-stream'


def bounds(header,size):
    if not header:return 200,0,size
    found=re.fullmatch(r'bytes=(\d*)-(\d*)',header.strip())
    if not found or not any(found.groups()):return 416,0,0
    left,right=found.groups()
    if not left:
        count=int(right)
        if count<=0:return 416,0,0
        start=max(0,size-count);end=size
    else:
        start=int(left);end=min(size,int(right)+1) if right else size
    if start>=size or start>=end:return 416,0,0
    return 206,start,end


def send(handler, kind, *, path=None, payload=None,stream=None,size=None):
    size=size if size is not None else path.stat().st_size if path else len(payload)
    status,start,end=bounds(handler.headers.get('Range'),size)
    extra={'Accept-Ranges':'bytes'}
    if path:extra['Cache-Control']='private, max-age=31536000, immutable'
    if status==416:extra['Content-Range']='bytes */'+str(size)
    elif status==206:extra['Content-Range']=f'bytes {start}-{end-1}/{size}'
    if kind=='application/octet-stream':extra['Content-Disposition']='attachment'
    handler.send_headers(status,kind,extra,length=end-start)
    if handler.command=='HEAD' or status==416:return
    if path or stream:
        source=path.open('rb') if path else stream
        try:
            source.seek(start);remaining=end-start
            while remaining:
                block=source.read(min(256*1024,remaining))
                if not block:break
                handler.wfile.write(block);remaining-=len(block)
        finally:
            if path:source.close()
    else:handler.wfile.write(payload[start:end])
