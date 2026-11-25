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
engine=create_engine(url,pool_pre_ping=True)
with engine.begin() as c: c.execute(text('CREATE TABLE IF NOT EXISTS aliases (address TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT \'\', favorite BOOLEAN NOT NULL DEFAULT FALSE, archived BOOLEAN NOT NULL DEFAULT FALSE, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'))
SCOPES=['https://www.googleapis.com/auth/gmail.readonly']
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
    return render_template_string(HEAD+'<main><h1>Temp Mail Pro</h1><form method="post"><input type="hidden" name="csrf" value="{{session.csrf}}"><input type="password" name="password" required placeholder="Senha"><button>Entrar</button></form>{{error}}</main>',error=error)
@app.post('/action')
def action():
    op=request.form.get('op'); address=request.form.get('address',''); note=request.form.get('note','')[:500]
    with engine.begin() as c:
        if op=='new':
            tag=request.form.get('tag','').strip().lower() or secrets.token_hex(6)
            if not re.fullmatch(r'[a-z0-9._-]{1,64}',tag): abort(400,'Alias inválido')
            address=base.split('@')[0]+'+'+tag+'@gmail.com'
            c.execute(text('INSERT INTO aliases(address,note) VALUES (:a,:n) ON CONFLICT(address) DO UPDATE SET archived=false'),{'a':address,'n':note})
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
            api=gmail(); result=api.users().messages().list(userId='me',q='to:'+selected,maxResults=50).execute()
            from email.utils import getaddresses
            for item in result.get('messages',[]):
                m=api.users().messages().get(userId='me',id=item['id'],format='metadata',metadataHeaders=['To','Cc','Delivered-To','From','Subject','Date']).execute()
                headers=m['payload']['headers']; h={x['name'].lower():x['value'] for x in headers}
                recipients=getaddresses([x['value'] for x in headers if x['name'].lower() in ('to','cc','delivered-to')])
                if selected.lower() in [a.lower() for _,a in recipients]: messages.append(dict(h, id=m['id'],snippet=m.get('snippet','')))
        except Exception: app.logger.warning('Gmail sync failed');error='Não foi possível consultar o Gmail. Verifique a configuração OAuth.'
    return render_template_string(HEAD+PAGE,rows=rows,selected=selected,messages=messages,error=error,base=base,connected=connected())
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
HEAD='''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Gmail Temp Mail Pro</title><style>body{background:#202225;color:#eee;font:16px Arial;margin:0}main{max-width:1050px;margin:30px auto;padding:20px}section,article{background:#303338;border:1px solid #555;padding:16px;margin:12px 0;border-radius:8px}input,button{padding:10px;margin:4px;background:#17191b;color:#eee;border:1px solid #777;border-radius:4px}button{cursor:pointer}a{color:#9acaff;overflow-wrap:anywhere}form{display:inline-block}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#bbb}</style>'''
PAGE='''<main><h1>Gmail Temp Mail Pro</h1><p>Conta central: {{base}}</p><section>Gmail: {{ "Conectado (token salvo)" if connected else "Desconectado" }} <form method="post" action="/oauth/connect"><input type="hidden" name="csrf" value="{{session.csrf}}"><button>Conectar / reconectar com Google</button></form></section><form method="post" action="/action"><input type="hidden" name="csrf" value="{{session.csrf}}"><button name="op" value="logout">Sair</button></form><section><h2>Gerar ou recuperar endereço</h2><form method="post" action="/action"><input type="hidden" name="csrf" value="{{session.csrf}}"><input name="tag" placeholder="Alias (vazio = aleatório)"><input name="note" placeholder="Anotação"><button name="op" value="new">Gerar / recuperar</button></form></section><section><h2>Histórico</h2>{% for r in rows %}<article><a href="{{url_for('index',address=r.address)}}">{{r.address}}</a> {% if r.favorite %}★{% endif %} {% if r.archived %}<small>Arquivado</small>{% endif %}<p>{{r.note}}</p><form method="post" action="/action"><input type="hidden" name="csrf" value="{{session.csrf}}"><input type="hidden" name="address" value="{{r.address}}"><button name="op" value="favorite">Favorito</button><button name="op" value="archive">Arquivar / restaurar</button><input name="note" value="{{r.note}}"><button name="op" value="note">Salvar nota</button></form></article>{% else %}Nenhum endereço.{% endfor %}</section><section><h2>Caixa de entrada</h2>{% if selected %}<p>{{selected}}</p><button onclick="navigator.clipboard.writeText(this.dataset.address)" data-address="{{selected}}">Copiar endereço</button><button onclick="location.reload()">Atualizar</button><p>{{error}}</p>{% for m in messages %}<article><a href="{{url_for('message',mid=m.id,address=selected)}}">{{m.subject or '(Sem assunto)'}}</a><p>{{m.from}} — {{m.date}}</p><p>{{m.snippet}}</p></article>{% else %}Nenhuma mensagem exibida.{% endfor %}{% else %}Selecione um endereço no histórico.{% endif %}</section></main>'''
