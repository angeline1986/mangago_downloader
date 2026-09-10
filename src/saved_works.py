from __future__ import annotations
import json
from pathlib import Path
PROJECT_DIR=Path(__file__).resolve().parents[1]
SAVED_WORKS_DIR=PROJECT_DIR/'data'/'saved_works'
SUPPORTED_PROVIDERS=frozenset({'comix','mangago','ridi'})
def list_saved_works(provider: str):
    provider=str(provider or '').strip().lower()
    if provider not in SUPPORTED_PROVIDERS: raise ValueError(f'Provider de obras salvas inválido: {provider}')
    path=SAVED_WORKS_DIR/f'{provider}.json'
    if not path.exists(): return []
    with path.open(encoding='utf-8') as f: payload=json.load(f)
    works=payload.get('works')
    if not isinstance(works,list): raise ValueError(f'Arquivo inválido: {path.name} não contém works como lista.')
    out=[]
    for i,item in enumerate(works,1):
        if not isinstance(item,dict): raise ValueError(f'Registro {i} inválido em {path.name}.')
        name=str(item.get('name') or '').strip(); url=str(item.get('url') or '').strip()
        if not name or not url: raise ValueError(f'Registro {i} inválido em {path.name}: name e url são obrigatórios.')
        out.append({'name':name,'url':url})
    return out
