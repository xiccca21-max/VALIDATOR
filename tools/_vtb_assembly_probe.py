
import hashlib, json, re, zlib
from pathlib import Path

TARGETS={
'951350a0c80d00d7fbc5256e5c1c0de7d391c463f7e667f89a94c9be1bc376b7',
'be7f59dfca957fe8d2ee02a717941e7283428668e3e46841e11fbf1ece8f461c',
}
def sha(b):
    if isinstance(b,str): b=b.encode()
    return hashlib.sha256(b).hexdigest()

def dec_stream(body):
    sm=re.search(rb'stream\r?\n(.*?)\n?endstream', body, re.S)
    if not sm: return None
    raw=sm.group(1)
    try: return zlib.decompress(raw.rstrip(b'\r\n'))
    except:
        try: return zlib.decompress(raw)
        except: return raw

def norm_w(w):
    pretty=re.sub(rb'\[\s*', b'[ ', w)
    pretty=re.sub(rb'\s*\]', b' ]', pretty)
    pretty=re.sub(rb'\s+', b' ', pretty.strip())
    return pretty

def balanced(data, start):
    depth=0
    for i in range(start,len(data)):
        if data[i:i+1]==b'[': depth+=1
        elif data[i:i+1]==b']':
            depth-=1
            if depth==0: return data[start:i+1]
    return b''

def assembly(pdf):
    m=re.search(rb'/Contents\s+(\d+)\s+0\s+R', pdf)
    content=b''
    if m:
        om=re.search(rf'{int(m.group(1))}\s+0\s+obj(.*?)endobj'.encode(), pdf, re.S)
        content=dec_stream(om.group(1)) or b''
    touni=b''; ff2=b''; cid=b''; w=b''
    for om in re.finditer(rb'(\d+)\s+0\s+obj(.*?)endobj', pdf, re.S):
        body=om.group(2)
        if b'/Subtype /Type0' not in body and b'/Subtype/Type0' not in body:
            continue
        tm=re.search(rb'/ToUnicode\s+(\d+)\s+0\s+R', body)
        if tm:
            ob=re.search(rf'{int(tm.group(1))}\s+0\s+obj(.*?)endobj'.encode(), pdf, re.S)
            touni=dec_stream(ob.group(1)) or b''
        dm=re.search(rb'/DescendantFonts\s*\[\s*(\d+)\s+0\s+R', body)
        if not dm: break
        dob=re.search(rf'{int(dm.group(1))}\s+0\s+obj(.*?)endobj'.encode(), pdf, re.S)
        dbody=dob.group(1)
        wm=re.search(rb'/W\s*\[', dbody)
        if wm: w=balanced(dbody, wm.end()-1)
        cm=re.search(rb'/CIDToGIDMap\s+(\d+)\s+0\s+R', dbody)
        if cm:
            cob=re.search(rf'{int(cm.group(1))}\s+0\s+obj(.*?)endobj'.encode(), pdf, re.S)
            cid=dec_stream(cob.group(1)) or b''
        fdm=re.search(rb'/FontDescriptor\s+(\d+)\s+0\s+R', dbody)
        if fdm:
            fdob=re.search(rf'{int(fdm.group(1))}\s+0\s+obj(.*?)endobj'.encode(), pdf, re.S)
            ffm=re.search(rb'/FontFile2\s+(\d+)\s+0\s+R', fdob.group(1))
            if ffm:
                fob=re.search(rf'{int(ffm.group(1))}\s+0\s+obj(.*?)endobj'.encode(), pdf, re.S)
                ff2=dec_stream(fob.group(1)) or b''
        break
    comps={
        'content': sha(content),
        'tounicode': sha(touni),
        'cidtogid': sha(cid),
        'fontfile2': sha(ff2),
        'w': sha(norm_w(w)),
    }
    return sha(json.dumps(comps, sort_keys=True, separators=(',',':')).encode()), comps

for p in [Path(r'C:\Users\fanis\OneDrive\Desktop\фейки\ВТБ фейк.pdf'), Path(r'C:\Users\fanis\OneDrive\Desktop\фейки\втб сбп.pdf')]:
    h,c=assembly(p.read_bytes())
    print(p.name, h, h in TARGETS)