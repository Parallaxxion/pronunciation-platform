"""Weighted DP syllable alignment; deterministic tie break: diagonal, deletion, insertion."""
import re,unicodedata
def numbered(value):
    value=value.lower().strip().replace('u:','v').replace('ü','v')
    tone=None; parts=[]
    for c in unicodedata.normalize('NFD',value):
        if c in '\u0304\u0301\u030c\u0300': tone=str('\u0304\u0301\u030c\u0300'.index(c)+1)
        elif c=='\u0308':
            if parts and parts[-1]=='u': parts[-1]='v'
        else: parts.append(c)
    value=''.join(parts)
    if not re.fullmatch(r'[a-zv]+[0-5]?',value): raise ValueError('Invalid syllable: '+value)
    return value[:-1]+('5' if value[-1]=='0' else value[-1]) if value[-1].isdigit() else value+(tone or '5')
def align(reference,hypothesis):
    a,b=[numbered(x) for x in reference],[numbered(x) for x in hypothesis]
    n,m=len(a),len(b)
    if max(n,m)>1000: raise ValueError('Split segment into <=1000 syllables')
    d=[[0]*(m+1) for _ in range(n+1)]
    for i in range(n+1): d[i][0]=4*i
    for j in range(m+1): d[0][j]=4*j
    def cost(x,y): return 0 if x==y else (1 if x[:-1]==y[:-1] else 4)
    for i in range(1,n+1):
        for j in range(1,m+1): d[i][j]=min(d[i-1][j-1]+cost(a[i-1],b[j-1]),d[i-1][j]+4,d[i][j-1]+4)
    ops=[];i=n;j=m
    while i or j:
        if i and j and d[i][j]==d[i-1][j-1]+cost(a[i-1],b[j-1]):
            ops.append(('equal' if a[i-1]==b[j-1] else 'replace',i-1,b[j-1]));i-=1;j-=1
        elif i and d[i][j]==d[i-1][j]+4: ops.append(('delete',i-1,None));i-=1
        else: ops.append(('insert',i,b[j-1]));j-=1
    errors=[]
    for op,i,v in reversed(ops):
        if op=='equal': continue
        if op=='insert':
            if errors and errors[-1]['type']=='insertion' and errors[-1]['boundary_index']==i: errors[-1]['actual']+=' '+v
            else: errors.append(dict(type='insertion',boundary_index=i,actual=v))
        elif op=='delete': errors.append(dict(type='omission',char_index=i,expected=a[i],actual=None))
        else: errors.append(dict(type='tone' if a[i][:-1]==v[:-1] else 'substitution',char_index=i,expected=a[i],actual=v))
    return errors
