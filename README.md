# Gmail Temp Mail Pro V2
Painel privado, Flask, Gmail API somente leitura, PostgreSQL Aiven. Não requer CMD.

1. Extraia o ZIP e envie os arquivos para um repositório privado GitHub.
2. No Aiven crie PostgreSQL e copie Service URI com sslmode=require.
3. No Render crie um Web Service Python conectado ao repositório. Build: `pip install -r requirements.txt`. Start: `gunicorn app:app --workers 1 --timeout 120`. Health check: `/health`.
4. Em Environment adicione DATABASE_URL (URI Aiven), ADMIN_PASSWORD (senha forte), GMAIL_ADDRESS (Gmail principal), GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET (cliente OAuth Web), SECRET_KEY (valor aleatório longo e permanente), PUBLIC_URL (URL HTTPS do serviço sem barra final). Não publique segredos no GitHub. Também pode usar Blueprint, sem banco Render.
5. No Google Cloud ative Gmail API, configure consentimento e escopo https://www.googleapis.com/auth/gmail.readonly, adicione seu Gmail como usuário de teste se necessário. No cliente Web adicione URI de redirecionamento exatamente PUBLIC_URL + /oauth/callback. Exemplo https://gmail-temp-mail-pro.onrender.com/oauth/callback (substitua pela URL real).
6. Abra o painel, entre com ADMIN_PASSWORD e clique Conectar / reconectar com Google. Autorize a conta configurada. O token é criptografado no Aiven usando SECRET_KEY; não altere essa chave sem reconectar.
7. Gere aliases aleatórios ou personalizados. Para recuperar um endereço antigo, selecione no histórico ou digite o mesmo sufixo. Arquivar não impede recebimento no Gmail.

Limites: Gmail aliases com + não são contas independentes; alguns sites rejeitam. Consulta manual até 50 resultados, filtrando cabeçalhos de destinatário; mensagens sem destinatário visível podem não aparecer. HTML é mostrado como texto, sem executar código. Mensagens permanecem no Gmail, não no banco. OAuth externo em teste pode expirar em 7 dias; reconecte quando necessário. Publicação OAuth pode exigir verificação Google. Painel de administrador único, sem limitação de tentativas de login; mantenha privado e use senha forte. Não testado com credenciais reais nem implantado. Não altere GMAIL_ADDRESS após cadastrar aliases sem avaliar o histórico.

## Atualização V3
Substitua os arquivos no GitHub. Preserve todas as variáveis do Render, especialmente SECRET_KEY e DATABASE_URL. Reconecte o Google no painel para conceder gmail.modify. Excluir endereço remove apenas o registro local; excluir mensagens move para a lixeira do Gmail. A limpeza percorre as páginas da busca e verifica o destinatário antes de mover. Mensagens com vários destinatários são movidas integralmente. Atualização automática opcional a cada 30 segundos. Nenhuma migração destrutiva do banco.
