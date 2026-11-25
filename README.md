# Gmail Temp Mail Pro
Painel privado de aliases Gmail reutilizáveis. Não cria contas Google independentes.

## Google Cloud
1. Crie um projeto em https://console.cloud.google.com/ e habilite Gmail API.
2. Configure a tela de consentimento OAuth (Google Auth Platform). Adicione sua conta Gmail como usuário de teste, se aplicável.
3. Crie um cliente OAuth do tipo aplicativo para computador. Baixe o JSON como credentials.json nesta pasta. Nunca envie esse arquivo ao GitHub.
4. No Windows, instale Python 3.11 ou superior. Abra o terminal nesta pasta e execute:
   `python -m pip install -r requirements.txt`
   `python oauth_setup.py`
5. Autorize a conta Gmail exclusiva do projeto. Guarde os três valores exibidos em segredo. Em modo Testing, refresh tokens de aplicativos externos com escopo Gmail normalmente expiram em 7 dias. Consulte os requisitos de publicação/verificação do Google antes de uso duradouro.

## GitHub e Render
1. Crie um repositório privado no GitHub e envie os arquivos do projeto, exceto credentials.json e quaisquer segredos.
2. No Render (https://dashboard.render.com/), escolha New > Blueprint, conecte o repositório e revise os planos e custos antes de confirmar. O render.yaml cria serviço web e PostgreSQL; não presume gratuidade.
3. Preencha ADMIN_PASSWORD (senha forte e exclusiva), GMAIL_ADDRESS (conta real, sem alias), GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e GMAIL_REFRESH_TOKEN. SECRET_KEY e DATABASE_URL são configurados pelo Blueprint.
4. Abra a URL fornecida pelo Render e entre com sua senha.

## Uso
Digite um alias ou deixe vazio para gerar aleatoriamente. Para recuperar um endereço, digite novamente o mesmo alias ou selecione o histórico. Arquivar não bloqueia recebimento. O botão Atualizar consulta até 50 mensagens recentes correspondentes; a mensagem completa é exibida como texto, inclusive HTML bruto quando não houver versão texto. Não há envio de e-mails, exclusão no Gmail ou armazenamento de conteúdo no banco. Mensagens sem o alias nos cabeçalhos consultados podem não aparecer. Sites podem rejeitar aliases com +.

## Segurança e operação
Use apenas como painel privado de um administrador. Não compartilhe a senha. Não exponha tokens. Mantenha backups do PostgreSQL; planos de banco podem expirar. Se a autorização for revogada ou expirar, execute novamente oauth_setup.py e atualize o token no Render. Não há limitação de tentativas de login implementada; para exposição pública, adicione proteção de acesso/rate limiting antes de usar. A aplicação não foi testada contra uma conta Gmail real ou implantação Render.
