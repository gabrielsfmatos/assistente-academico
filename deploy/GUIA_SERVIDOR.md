# Guia do servidor (Oracle Cloud + Tailscale)

Coloca o bot e o site no ar 24 horas, numa máquina gratuita da Oracle.
O site fica acessível de qualquer navegador (Tailscale Funnel, com HTTPS) e protegido por senha.

```
qualquer navegador ──(HTTPS, Tailscale Funnel)──> servidor Oracle
                                        ├── bot do Telegram  (busca mensagens no Telegram)
                                        ├── site             (127.0.0.1:8000, só a própria máquina)
                                        ├── academico.db     (banco, disco permanente)
                                        └── backup diário    (backups/ + cópia no seu Telegram)
```

Tempo estimado: 1 a 2 horas. Comandos com `PS>` são no PowerShell do seu PC;
com `$` são no servidor (depois do `ssh`).

**Segurança, sempre:** nunca mande para ninguém (nem no chat) a chave `oracle.key`,
o `.env` ou a senha do site. Nunca abra a porta 8000 na Oracle: o site chega à internet pelo
Tailscale Funnel, que não precisa de nenhuma porta aberta. Como o site é público, a senha do site
deve ter **12 caracteres ou mais**.

---

## 1. Criar a máquina

No painel da Oracle (região **Brazil East (Sao Paulo)**):
**Menu ☰ → Computação → Instâncias → Criar instância**.

- **Nome:** `academico`
- **Imagem:** Canonical Ubuntu 24.04 (a normal, não a "Minimal")
- **Forma:** Ampere → `VM.Standard.A1.Flex`, **1 OCPU e 1 GB de memória**
  - Confira a etiqueta **"Always Free-eligible"**.
  - Por que só 1 GB: a Oracle pode recuperar máquinas gratuitas ociosas. Nas máquinas Ampere,
    a máquina só conta como ociosa se, por 7 dias, CPU, rede **e memória** ficarem abaixo de 20%.
    O sistema usa uns 400 MB; com 1 GB isso passa de 20%, com 6 GB não passaria.
    O `setup.sh` cria uma memória de reserva (swap) para compensar.
- **Rede:** padrão (nova VCN, sub-rede pública, IPv4 público marcado)
- **Chaves SSH:** "Gerar um par de chaves para mim" → baixe a **chave privada** e salve como
  `C:\Users\gabri\.ssh\oracle.key` (fora da pasta do projeto).
- **Criar.** Anote o **IP público** que aparece na página da instância.

Sem capacidade ("Out of capacity")? Tente outro domínio de falha ou mais tarde.
Último recurso: `VM.Standard.E2.1.Micro` (AMD, 1 GB, também gratuita). Atenção: nela a regra de
memória não vale, então o risco de recuperação por ociosidade é maior. O backup diário no
Telegram (etapa 6) garante que nenhum dado se perde nesse caso.

**Alerta de gastos:** Menu ☰ → Faturamento → Orçamentos → orçamento de valor 1 com alerta em 100%.

## 2. Entrar no servidor

```powershell
PS> icacls "C:\Users\gabri\.ssh\oracle.key" /inheritance:r
PS> icacls "C:\Users\gabri\.ssh\oracle.key" /grant:r "$($env:USERNAME):(R)"
PS> ssh -i "C:\Users\gabri\.ssh\oracle.key" ubuntu@IP_DO_SERVIDOR
```

Na primeira vez, responda `yes`. Você está dentro quando aparecer `ubuntu@academico:~$`.

## 3. Baixar o código (GitHub)

O repositório é privado, então o servidor precisa de uma chave própria, **só de leitura**:

```bash
$ ssh-keygen -t ed25519 -C "servidor-oracle" -f ~/.ssh/github -N ""
$ cat ~/.ssh/github.pub
```

Copie a linha que aparecer (começa com `ssh-ed25519`). No GitHub: repositório
**assistente-academico → Settings → Deploy keys → Add deploy key**. Título `servidor-oracle`,
cole a chave e **deixe "Allow write access" desmarcado**.

```bash
$ printf 'Host github.com\n  IdentityFile ~/.ssh/github\n' >> ~/.ssh/config
$ git clone git@github.com:gabrielsfmatos/assistente-academico.git
$ mkdir -p ~/assistente-academico/data
```

## 4. Levar o banco e o .env (eles não vão para o GitHub)

**Antes: pare o bot no seu PC** (Ctrl + C no terminal dele). A partir de agora o banco "oficial"
é o do servidor. Dois bots com o mesmo token dão erro de conflito no Telegram.

Num PowerShell **novo** no PC, na pasta do projeto:

```powershell
PS> cd C:\Users\gabri\dev\assistente-academico
PS> scp -i "C:\Users\gabri\.ssh\oracle.key" .env academico.db ubuntu@IP_DO_SERVIDOR:~/assistente-academico/
PS> scp -i "C:\Users\gabri\.ssh\oracle.key" data\uso_telegram.jsonl ubuntu@IP_DO_SERVIDOR:~/assistente-academico/data/
```

Confira se o `.env` tem a linha `SITE_PASSWORD=...` preenchida.

## 5. Instalar e ligar tudo

De volta ao servidor:

```bash
$ cd ~/assistente-academico
$ bash deploy/setup.sh
```

O script ajusta o fuso horário, instala as bibliotecas, roda os testes e liga o bot, o site e o
backup diário. No fim, os dois serviços devem aparecer como `active (running)`.

**Teste:** mande "quantas faltas tenho em AP?" para o bot no Telegram. Se responder, o bot já
está rodando no servidor (pode desligar o PC).

## 6. Site acessível de qualquer navegador (Tailscale Funnel)

O Tailscale leva o site até a internet com HTTPS e um endereço fixo, sem domínio próprio e sem
abrir portas na Oracle. Quem tem o endereço vê a tela de login; os dados só com a senha.

No servidor:

```bash
$ curl -fsSL https://tailscale.com/install.sh | sh
$ sudo tailscale up
```

Abra o link que aparecer e entre com a sua conta (Google serve). Depois:

```bash
$ sudo tailscale funnel --bg 8000
```

Se ele pedir para ativar HTTPS ou o Funnel, abra o link indicado e ative. O comando mostra o
endereço do site, algo como `https://academico.tail1234.ts.net`. Ele abre em qualquer navegador,
sem app. Confira com `sudo tailscale funnel status` (deve dizer "Funnel on").

- **Celular:** abra o endereço, entre marcando "Manter conectado" e use "Adicionar à Tela de Início".
- **Computador de outra pessoa:** entre **sem** marcar "Manter conectado" e use "Sair deste
  aparelho" no fim do Histórico. O login também some ao fechar o navegador.
- **Segurança extra:** depois de 5 senhas erradas em 15 minutos, o login fica bloqueado por
  15 minutos.
- **Voltar a ser só privado** (só aparelhos com o app Tailscale): `sudo tailscale funnel --bg off`
  e depois `sudo tailscale serve --bg 8000`.

**Teste do backup:**

```bash
$ sudo systemctl start academico-backup.service
```

Deve chegar no Telegram um arquivo `academico-....db`, sem som de notificação.

---

## Dia a dia

| Para... | Comando (no servidor) |
|---|---|
| Atualizar depois de um `git push` | `cd ~/assistente-academico && bash deploy/update.sh` |
| Ver o que o bot está fazendo | `journalctl -u academico-bot -f` (Ctrl + C para sair) |
| Ver erros do site | `journalctl -u academico-site -n 50` |
| Reiniciar | `sudo systemctl restart academico-bot academico-site` |
| Relatório de uso | `.venv/bin/python -m scripts.usage_report` |
| Ver quando roda o backup | `systemctl list-timers academico-backup.timer` |

**Trabalhar no código pelo PC:** edite, rode os testes, faça commit e push, e rode
`deploy/update.sh` no servidor. Para testar no PC com dados reais, baixe uma cópia do banco
(`scp ... ubuntu@IP:~/assistente-academico/academico.db .`) e **não ligue o bot no PC**.

**Restaurar um backup:**

```bash
$ cd ~/assistente-academico
$ sudo systemctl stop academico-bot academico-site
$ cp backups/academico-AAAA-MM-DD_0300.db academico.db
$ sudo systemctl start academico-bot academico-site
```

O backup que chega no Telegram serve se o servidor for perdido: baixe o arquivo, renomeie para
`academico.db` e envie com `scp` (etapa 4) para a máquina nova.

## Se algo der errado

- **`setup.sh` parou com "FALTA":** copie o arquivo indicado (etapa 4) e rode o setup de novo.
- **Bot não responde:** `journalctl -u academico-bot -n 50`. "Conflict" = o bot ainda está ligado
  no PC; desligue lá.
- **Site não abre no celular:** confira se o Tailscale está ativado no celular e
  `sudo tailscale serve status` no servidor. `curl -I http://127.0.0.1:8000/login` no servidor
  deve responder `200`.
- **Data errada nas faltas:** `timedatectl` deve mostrar `America/Sao_Paulo`.
