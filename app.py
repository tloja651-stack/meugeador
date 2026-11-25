import os, secrets, re, hmac
from cryptography.fernet import Fernet
import hashlib, base64
from google_auth_oauthlib.flow import Flow
from flask import url_for
from flask import Flask, request, session, redirect, render_template_string, abort
from sqlalchemy import create_engine, text
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
app=Flask(__name__)
app.secret_key=os.environ['SECRET_KEY']
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE='Lax')
base=os.environ['GMAIL_ADDRESS'].lower()
if not re.fullmatch(r'[a-z0-9.]+@gmail\.com',base): raise ValueError('GMAIL_ADDRESS inválido')
url=os.environ['DATABASE_URL'].replace('postgres://','postgresql://',1)
url=url.replace('postgresql://','postgresql+psycopg2://',1)
engine=create_engine(url,pool_pre_ping=True)
with engine.begin() as c: c.execute(text('CREATE TABLE IF NOT EXISTS aliases (address TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT \'\', favorite BOOLEAN NOT NULL DEFAULT FALSE, archived BOOLEAN NOT NULL DEFAULT FALSE, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'))
SCOPES=['https://www.googleapis.com/auth/gmail.modify']
with engine.begin() as c:
    c.execute(text('CREATE TABLE IF NOT EXISTS oauth_store (id INTEGER PRIMARY KEY, token TEXT NOT NULL)'))
cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256(app.secret_key.encode()).digest()))
def flow(state=None):
    return Flow.from_client_config({'web':{'client_id':os.environ['GOOGLE_CLIENT_ID'],'client_secret':os.environ['GOOGLE_CLIENT_SECRET'],'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token'}},scopes=SCOPES,state=state,redirect_uri=os.environ['PUBLIC_URL'].rstrip('/')+'/oauth/callback')
def connected():
    with engine.connect() as c: return bool(c.execute(text('SELECT 1 FROM oauth_store WHERE id=1')).first())
@app.post('/oauth/connect')
def connect():
    f=flow(); url,state=f.authorization_url(access_type='offline',prompt='consent',login_hint=base)
    session['oauth_state']=state
    session['oauth_verifier']=f.code_verifier
    return redirect(url)
@app.get('/oauth/callback')
def callback():
    state=session.pop('oauth_state',None)
    verifier=session.pop('oauth_verifier',None)
    if not state or not hmac.compare_digest(state,request.args.get('state','')): abort(400,'Estado OAuth inválido')
    if not request.args.get('code'): return 'Autorização cancelada. Volte ao painel.',400
    try:
        f=flow(state); f.code_verifier=verifier; f.fetch_token(code=request.args['code'])
        cred=f.credentials
        api=build('gmail','v1',credentials=cred,cache_discovery=False)
        if api.users().getProfile(userId='me').execute()['emailAddress'].lower()!=base: return 'Autorize o Gmail configurado no Render.',400
        if not cred.refresh_token: return 'Google não forneceu token de renovação. Autorize novamente.',400
        token=cipher.encrypt(cred.refresh_token.encode()).decode()
        with engine.begin() as c: c.execute(text('INSERT INTO oauth_store VALUES (1,:t) ON CONFLICT(id) DO UPDATE SET token=:t'),{'t':token})
    except Exception:
        return 'Falha na autorização. Confira as credenciais, permissões e URI de retorno.',400
    return redirect('/')
def gmail():
    with engine.connect() as c: token=c.execute(text('SELECT token FROM oauth_store WHERE id=1')).scalar()
    if not token: raise ValueError('Gmail desconectado')
    cred=Credentials(None,refresh_token=cipher.decrypt(token.encode()).decode(),token_uri='https://oauth2.googleapis.com/token',client_id=os.environ['GOOGLE_CLIENT_ID'],client_secret=os.environ['GOOGLE_CLIENT_SECRET'],scopes=SCOPES)
    cred.refresh(Request())
    return build('gmail','v1',credentials=cred,cache_discovery=False)
@app.before_request
def guard():
    if request.path=='/health': return
    if 'csrf' not in session: session['csrf']=secrets.token_hex(32)
    if request.method=='POST' and not hmac.compare_digest(request.form.get('csrf',''),session['csrf']): abort(403)
    if request.endpoint!='login' and not session.get('auth'): return redirect('/login')
@app.get('/health')
def health(): return 'OK'
@app.route('/login',methods=['GET','POST'])
def login():
    error=''
    if request.method=='POST':
        if hmac.compare_digest(request.form.get('password','').encode(),os.environ['ADMIN_PASSWORD'].encode()):
            session.clear();session['auth']=True;return redirect('/')
        error='Senha incorreta'
    return render_template_string(HEAD+'<main class="login"><section><h1>Temp Mail Pro V4</h1><form class="stack" method="post"><input type="hidden" name="csrf" value="{{session.csrf}}"><input type="password" name="password" required placeholder="Senha"><button>Entrar</button></form><p class="error">{{error}}</p></section></main>',error=error)
@app.post('/action')
def action():
    op=request.form.get('op'); address=request.form.get('address',''); note=request.form.get('note','')[:500]
    with engine.begin() as c:
        if op=='new':
            tag=request.form.get('tag','').strip().lower() or secrets.token_hex(6)
            if not re.fullmatch(r'[a-z0-9._-]{1,64}',tag): abort(400,'Alias inválido')
            address=base.split('@')[0]+'+'+tag+'@gmail.com'
            c.execute(text('INSERT INTO aliases(address,note) VALUES (:a,:n) ON CONFLICT(address) DO UPDATE SET archived=false'),{'a':address,'n':note})
        elif op=='delete': c.execute(text('DELETE FROM aliases WHERE address=:a'),{'a':address}); address=''
        elif op=='favorite': c.execute(text('UPDATE aliases SET favorite=NOT favorite WHERE address=:a'),{'a':address})
        elif op=='archive': c.execute(text('UPDATE aliases SET archived=NOT archived WHERE address=:a'),{'a':address})
        elif op=='note': c.execute(text('UPDATE aliases SET note=:n WHERE address=:a'),{'a':address,'n':note})
        elif op=='logout': session.clear();return redirect('/login')
        else: abort(400)
    return redirect(url_for('index',address=address))
@app.get('/')
def index():
    with engine.connect() as c: rows=c.execute(text('SELECT * FROM aliases ORDER BY favorite DESC, created DESC')).mappings().all()
    selected=request.args.get('address',''); messages=[]; error=''
    if selected in [r['address'] for r in rows]:
        try:
            api=gmail(); result=api.users().messages().list(userId='me',q='in:anywhere -in:trash -in:spam to:'+selected,maxResults=50).execute()
            from email.utils import getaddresses
            for item in result.get('messages',[]):
                m=api.users().messages().get(userId='me',id=item['id'],format='metadata',metadataHeaders=['To','Cc','Delivered-To','From','Subject','Date']).execute()
                headers=m['payload']['headers']; h={x['name'].lower():x['value'] for x in headers}
                recipients=getaddresses([x['value'] for x in headers if x['name'].lower() in ('to','cc','delivered-to')])
                if selected.lower() in [a.lower() for _,a in recipients]: messages.append(dict(h, id=m['id'],snippet=m.get('snippet','')))
        except Exception: app.logger.warning('Gmail sync failed');error='Não foi possível consultar o Gmail. Verifique a configuração OAuth.'
    return render_template_string(HEAD+PAGE,rows=rows,selected=selected,messages=messages,error=error,base=base,connected=connected())
@app.post('/trash')
def trash():
    from email.utils import getaddresses
    selected=request.form.get('address','')
    with engine.connect() as c:
        if not c.execute(text('SELECT 1 FROM aliases WHERE address=:a'),{'a':selected}).first(): abort(404)
    try:
        api=gmail(); service=api.users().messages(); ids=[]
        if request.form.get('all')=='1':
            page=None
            while True:
                result=service.list(userId='me',q='in:anywhere -in:trash -in:spam to:'+selected,maxResults=100,pageToken=page).execute()
                ids.extend(x['id'] for x in result.get('messages',[])); page=result.get('nextPageToken')
                if not page: break
        else: ids=[request.form.get('mid','')]
        for mid in ids:
            m=service.get(userId='me',id=mid,format='metadata',metadataHeaders=['To','Cc','Delivered-To']).execute()
            recipients=getaddresses([x['value'] for x in m['payload']['headers'] if x['name'].lower() in ('to','cc','delivered-to')])
            if selected.lower() in [a.lower() for _,a in recipients]: service.trash(userId='me',id=mid).execute()
    except Exception:
        return render_template_string(HEAD+'<main><section><h2>Não foi possível concluir a exclusão</h2><p>Reconecte o Google para conceder a nova permissão. Algumas mensagens podem já ter sido movidas.</p><a href="{{url_for(\'index\',address=selected)}}">Voltar</a></section></main>',selected=selected),400
    return redirect(url_for('index',address=selected))
@app.get('/message/<mid>')
def message(mid):
    import base64
    from email import policy
    from email.parser import BytesParser
    selected=request.args.get('address','')
    with engine.connect() as c:
        if not c.execute(text('SELECT 1 FROM aliases WHERE address=:a'),{'a':selected}).first(): abort(404)
    raw=gmail().users().messages().get(userId='me',id=mid,format='raw').execute()['raw']; msg=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)))
    from email.utils import getaddresses
    if selected.lower() not in [a.lower() for _,a in getaddresses([str(v) for k,v in msg.items() if k.lower() in ('to','cc','delivered-to')])]: abort(404)
    part=msg.get_body(preferencelist=('plain','html')); body=part.get_content() if part else ''
    return render_template_string(HEAD+'<main><a href="{{url_for(\'index\',address=selected)}}">Voltar</a><h2>{{subject}}</h2><p>{{sender}}</p><pre>{{body}}</pre></main>',selected=selected,subject=msg['subject'],sender=msg['from'],body=body)
HEAD='''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Gmail Temp Mail Pro V4</title><style>
*{box-sizing:border-box}body{background:#141619;color:#e9edf2;font:15px system-ui,sans-serif;margin:0}main{max-width:1250px;margin:auto;padding:24px}header,.bar,.actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:space-between}h1{font-size:25px;margin:0}h2{font-size:19px;margin:0 0 16px}p{overflow-wrap:anywhere}section,article{background:#22262b;border:1px solid #3b4149;padding:18px;margin:12px 0;border-radius:12px}article{background:#1a1e23;padding:12px}input,button{font:inherit;padding:10px 12px;background:#15181c;color:#eee;border:1px solid #505963;border-radius:7px;max-width:100%;min-height:42px}button{cursor:pointer}button:hover{background:#39414c}button.primary{background:#245da5;border-color:#5289cf}button.danger{color:#ffb4b4;border-color:#854747}a{color:#9acaff;overflow-wrap:anywhere}form{margin:0}pre{white-space:pre-wrap;overflow-wrap:anywhere}small,.muted{color:#aeb7c3}.layout{display:grid;grid-template-columns:minmax(280px, 370px) minmax(0,1fr);gap:18px;align-items:start}.layout>*{min-width:0}.stack{display:grid;gap:8px}.stack input{width:100%}.actions{justify-content:flex-start}.selected{border-color:#6399db}.status{color:#9ee0b3}.error{color:#ffb4b4}.address{font-weight:600;overflow-wrap:anywhere}.history{max-height:65vh;overflow:auto}.login{max-width:460px;margin:12vh auto} @media(max-width:760px){main{padding:12px}.layout{grid-template-columns:1fr}.inbox{grid-row:1}.history{max-height:45vh}section{padding:14px}h1{font-size:21px}button,input{font-size:16px}.actions button{flex:1}.bar{align-items:flex-start}}
.entry{display:flex;align-items:center;gap:6px;border-bottom:1px solid #3b4149;padding:5px 3px}.entry[hidden]{display:none}.entry.selected{background:#26394e;border-radius:6px}.entry a{flex:1;min-width:0;padding:9px 4px;text-decoration:none;font-size:13px}.entry a:hover{text-decoration:underline}.mini{min-height:32px;width:32px;padding:0;font-size:20px}.history{margin-top:8px}details{margin:0 0 12px}summary{cursor:pointer;color:#aeb7c3;padding:8px 0} @media(max-width:760px){.inbox{grid-row:auto}.history{max-height:35vh}.entry a{font-size:14px}.mini{min-height:40px;width:40px}.layout{gap:0}}
</style>'''
PAGE='''<main><header><div><h1>Temp Mail Pro <small>V4</small></h1><p class="muted">{{base}}</p></div><form method="post" action="/action"><input type="hidden" name="csrf" value="{{session.csrf}}"><button name="op" value="logout">Sair</button></form></header>
<section class="bar"><span class="status">{{ "Gmail: token salvo" if connected else "Gmail desconectado" }}</span><form method="post" action="/oauth/connect"><input type="hidden" name="csrf" value="{{session.csrf}}"><button>Conectar / reconectar Google</button></form></section>
<section><h2>Gerar ou recuperar endereço</h2><form method="post" action="/action" class="stack"><input type="hidden" name="csrf" value="{{session.csrf}}"><input name="tag" placeholder="Alias personalizado (vazio = aleatório)"><input name="note" placeholder="Anotação opcional"><button class="primary" name="op" value="new">Gerar / recuperar</button></form></section>
<div class="layout"><section><h2>Meus e-mails · {{rows|length}}</h2><input id="search" aria-label="Buscar endereço" placeholder="Buscar endereço ou nota" style="width:100%" oninput="document.querySelectorAll('.entry').forEach(e=>e.hidden=!e.dataset.search.toLowerCase().includes(this.value.toLowerCase()))"><div class="history">{% for r in rows %}<div class="entry {{'selected' if selected==r.address else ''}}" data-search="{{r.address}} {{r.note}}"><a class="address" href="{{url_for('index',address=r.address)}}#inbox">{{'★ ' if r.favorite else ''}}{{r.address}}</a><form method="post" action="/action" onsubmit="return confirm('Excluir endereço do histórico? As mensagens serão mantidas.')"><input type="hidden" name="csrf" value="{{session.csrf}}"><input type="hidden" name="address" value="{{r.address}}"><button class="mini danger" name="op" value="delete" title="Excluir endereço" aria-label="Excluir {{r.address}}">×</button></form></div>{% else %}<p>Nenhum endereço.</p>{% endfor %}</div></section>
<section class="inbox" id="inbox"><h2>Caixa de entrada</h2>{% if selected %}<p class="address">{{selected}}</p>{% for r in rows if r.address==selected %}<details><summary>Opções do endereço</summary><form method="post" action="/action" class="stack"><input type="hidden" name="csrf" value="{{session.csrf}}"><input type="hidden" name="address" value="{{r.address}}"><div class="actions"><button name="op" value="favorite">{{'Remover favorito' if r.favorite else 'Favorito'}}</button><button name="op" value="archive">{{'Restaurar' if r.archived else 'Arquivar'}}</button></div><input name="note" value="{{r.note}}" placeholder="Nota"><button name="op" value="note">Salvar nota</button></form></details>{% endfor %}<div class="actions"><button data-address="{{selected}}" onclick="navigator.clipboard.writeText(this.dataset.address)">Copiar endereço</button><button onclick="location.reload()">Atualizar</button><form method="post" action="/trash" onsubmit="return confirm('Mover todas as mensagens deste endereço para a lixeira do Gmail?')"><input type="hidden" name="csrf" value="{{session.csrf}}"><input type="hidden" name="address" value="{{selected}}"><button class="danger" name="all" value="1">Limpar caixa</button></form></div><p class="muted">{{messages|length}} mensagens exibidas · até 50 por consulta</p><p class="error">{{error}}</p>{% for m in messages %}<article><a href="{{url_for('message',mid=m.id,address=selected)}}">{{m.subject or '(Sem assunto)'}}</a><p class="muted">{{m.from}} — {{m.date}}</p><p>{{m.snippet}}</p><form method="post" action="/trash" onsubmit="return confirm('Mover mensagem para a lixeira?')"><input type="hidden" name="csrf" value="{{session.csrf}}"><input type="hidden" name="address" value="{{selected}}"><input type="hidden" name="mid" value="{{m.id}}"><button class="danger">Excluir mensagem</button></form></article>{% else %}<p>Nenhuma mensagem exibida.</p>{% endfor %}<label><input type="checkbox" id="auto"> Atualizar automaticamente (30 s)</label><script>let a=document.getElementById('auto');a.checked=sessionStorage.getItem('auto')==='1';a.onchange=()=>sessionStorage.setItem('auto',a.checked?'1':'0');setInterval(()=>{if(a.checked&&!document.hidden&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName))location.reload()},30000)</script>{% else %}<p>Selecione um endereço no histórico ou gere um novo.</p>{% endif %}</section></div></main>'''
