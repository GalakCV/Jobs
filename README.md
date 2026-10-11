# remote-junior-jobs

Crawler de vagas **100% remotas** e **explicitamente júnior** em três áreas:

| Área | Exemplos de cargos aceitos |
|---|---|
| DevOps / SRE / Platform | Junior DevOps Engineer, Jr. SRE, Junior Platform Engineer |
| Cibersegurança | Junior Security Analyst, Entry-Level SOC Analyst, SOC Analyst Tier 1, Junior AppSec |
| Infra / Cloud / SysAdmin | Entry Level Cloud Support Engineer, Junior Linux SysAdmin, Cloud Engineer I |

Regiões aceitas: **Estados Unidos, Canadá, Austrália** e vagas **globais** (Worldwide / Anywhere).

---

## Por que Python

O trabalho é dominado por I/O de rede e processamento de texto (HTML, RSS, regex), e não por CPU. Python tem as bibliotecas mais maduras para isso (`requests`, `BeautifulSoup`, `defusedxml`), SQLite nativo e é fácil de ajustar. Go só valeria a pena com milhares de fontes em paralelo.

---

## Fontes

| Fonte | Tipo | Observação |
|---|---|---|
| [Himalayas](https://himalayas.app/api) | API JSON pública | busca com filtro `seniority=Entry-level` |
| [Jobicy](https://jobicy.com/jobs-rss-feed) | API JSON pública | categorias DevOps & Infra, Cybersecurity, Technical Support |
| [Remotive](https://remotive.com/api/remote-jobs) | API JSON pública | pede poucas chamadas por dia (o cache cuida disso) |
| [Remote OK](https://remoteok.com/api) | API JSON pública | por tags: devops, sysadmin, security, infosec, cloud |
| [We Work Remotely](https://weworkremotely.com/remote-job-rss-feed) | RSS público | categoria DevOps/Sysadmin + feed geral |
| LinkedIn | HTML (busca "guest") | **desligado por padrão**, veja o aviso abaixo |

Todas as fontes oficiais pedem atribuição: cada vaga salva mantém o link original da fonte.

**Fontes citadas no pedido que ficaram de fora, e por quê:**

- **Indeed**: não tem mais API pública (o programa Publisher foi encerrado) e usa proteção anti-bot agressiva. Um scraper ali quebraria toda semana e exigiria técnicas de evasão que este projeto deliberadamente não usa.
- **Remote.co**: não oferece API nem RSS. Seletores HTML "chutados" seriam código quebrado; se você quiser adicioná-lo, veja a seção *Adicionar uma fonte nova*.
- **LinkedIn**: implementado, mas **desligado**. Os Termos de Uso do LinkedIn proíbem coleta automatizada e o site bloqueia IPs rapidamente. Se ligar (`sources.linkedin.enabled: true`), use em volume baixo e por sua conta e risco. Ao primeiro bloqueio a fonte é pulada; o código não tenta contornar.

---

## Instalação

Requer **Python 3.10+**.

```bash
cd remote-junior-jobs
python -m venv .venv

# Linux / macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
cp .env.example .env        # opcional: só para notificações (Windows: copy .env.example .env)
```

---

## Uso

```bash
# Execução completa e abre o relatório HTML no navegador
python -m jobcrawler run --open

# Execução completa: coleta, filtra, salva no SQLite, exporta e notifica
python -m jobcrawler run

# Relatório HTML com o histórico do banco (sem acessar a rede)
python -m jobcrawler report --days 14 --open

# Gera também output/rejections.csv com o MOTIVO de cada vaga descartada
python -m jobcrawler run --explain

# Testar sem gravar no banco nem notificar
python -m jobcrawler run --dry-run

# Só algumas fontes
python -m jobcrawler run --sources himalayas,jobicy

# Repetir a cada 6 horas (Ctrl+C para sair)
python -m jobcrawler run --loop-hours 6

# Ver vagas encontradas nos últimos 3 dias
python -m jobcrawler list --days 3

# Testar o filtro com um título, sem acessar a rede
python -m jobcrawler check "Junior Cloud Security Engineer" --location "Remote - Canada"
python -m jobcrawler check "Junior SRE" --location USA --description-file descricao.txt

# Log detalhado: mostra a decisão do filtro para cada vaga
python -m jobcrawler -v run
```

Códigos de saída de `run`: `0` sucesso, `1` erro de configuração/arquivo, `2` **todas** as fontes falharam (útil para alertas no cron).

---

## Saídas

| Arquivo | Conteúdo |
|---|---|
| `output/jobs_latest.html` | **relatório visual** da última execução (abra no navegador) |
| `output/report.html` | gerado por `report`: histórico do banco dos últimos N dias |
| `output/jobs_latest.csv` | vagas aceitas na última execução (abre direto no Excel/Sheets, com acentos) |
| `output/jobs_latest.json` | o mesmo, em JSON, com `total` e `new` |
| `output/jobs_AAAAMMDD-HHMMSS.*` | cópia datada de cada execução |
| `output/rejections.csv` | com `--explain`: etapa e motivo de cada descarte |
| `data/jobs.db` | SQLite com o histórico; tabela `jobs` (deduplicada) e `runs` (estatísticas) |
| `logs/crawler.log` | log rotacionado (5 arquivos de 1 MB) |

### Relatório HTML

Um único arquivo, sem dependências, que abre em qualquer navegador (inclusive no celular):

- Barra colorida com a proporção de vagas por área; clique num segmento para filtrar.
- Busca por cargo, empresa ou tecnologia (ignora acentos), filtro por região e "Só novas".
- Cada vaga mostra empresa, regiões, fuso exigido, salário, por que foi considerada júnior, data relativa ("ontem", "há 3 dias") e um trecho da descrição.
- "Detalhes da execução" no rodapé mostra quantas vagas cada fonte trouxe, erros e por que as outras foram descartadas.
- Modo escuro automático. Todo texto vindo das fontes é escapado, e só links `http(s)` ficam clicáveis.

Para desligar algum formato, edite `storage.export_formats` no `config.yaml`.

Colunas do CSV: Publicada em · Título · Empresa · Área · Localização · Regiões · Fuso exigido · Por que é júnior · Salário · Fonte · Nova? · Link.

A coluna **"Por que é júnior"** mostra exatamente qual evidência foi usada (ex.: `título: 'junior'` ou `fonte: 'Entry-level'`), para você auditar cada resultado.

---

## Como o filtro funciona

Tudo é configurável em `config.yaml`. O texto é normalizado antes da comparação (minúsculo e sem acentos), então `Sênior`, `Senior` e `SENIOR` são a mesma coisa, e os termos usam limites de palavra (`sr` **não** casa com `SRE`; `intern` **não** casa com `internal`).

Ordem das verificações (a primeira reprovação encerra):

1. **Idade**: descarta vagas com mais de `max_age_days` (padrão 30).
2. **Remoto**: descarta `hybrid`, `on-site`, `in-office`, `presencial` no título/localização.
3. **Área** (whitelist no título): Security → DevOps/SRE/Platform → Infra/Cloud/SysAdmin. Exclui falsos positivos como "Cloud **Sales**".
4. **Blacklist de senioridade no título** (regra crítica): intern, trainee, estágio, pleno, mid, intermediate, II/III/IV, Tier 2, senior, sr, lead, principal, staff, manager, head, director, architect, experienced, entre outros.
5. **Nível declarado pela fonte**: se Himalayas/Jobicy disserem "Mid-level" ou "Senior", descarta.
6. **Descrição**: anos de experiência exigidos e frases de nível (veja abaixo).
7. **Júnior explícito**: precisa de um marcador (junior, jr, entry-level, associate, tier 1, "Engineer I"…) no título, ou nível "Entry-level/Junior" informado pela fonte.
8. **Região**: US, CA, AU ou Global. "APAC" conta como Austrália; vaga sem localização passa marcada como `NÃO INFORMADO` (configurável).

### Descrição: modo `smart` (padrão) vs `strict`

Você pediu que termos da blacklist **na descrição** também descartem a vaga. Aplicado ao pé da letra, isso elimina praticamente todas as vagas júnior, porque descrições quase sempre trazem frases como *"you'll report to the engineering **manager**"*, *"work alongside **senior** engineers"* ou *"**lead** incident retrospectives"*. Por isso há dois modos:

- **`smart`** (padrão): descarta por **frases que descrevem o nível da própria vaga** (*"this is a senior role"*, *"mid-level position"*, *"internship"*, *"vaga pleno"*) e por **anos de experiência**: com `max_years_experience: 2`, qualquer exigência de **3+ anos** descarta a vaga (cobre o "Experienced com mais de 3-5 anos"). Faixas usam o limite inferior ("3-5 years" = 3) e, havendo várias exigências, vale a maior.
- **`strict`**: descarta se **qualquer** termo da blacklist aparecer **em qualquer lugar** da descrição. Fiel à regra literal; espere pouquíssimos resultados.

Troque em `filters.description_mode`. Rode com `--explain` e confira o `rejections.csv` para calibrar.

### Ajustes comuns

- Incluir help desk / service desk: descomente as linhas no fim de `filters.areas.infra_cloud_sysadmin`.
- Ser ainda mais rígido: `trust_source_seniority: false` (exige "junior" no título) e `allow_unknown_location: false`.
- Aceitar até 3 anos de experiência: `max_years_experience: 3`.
- Termo com `: ` (dois-pontos e espaço) no YAML precisa de aspas, senão vira dicionário. O programa avisa se isso acontecer.

---

## Notificações (opcional)

Habilite em `config.yaml` → `notifications` e preencha o `.env`. Só vagas **novas** são enviadas, no máximo `max_per_run` por execução. Uma vaga só é marcada como notificada quando todos os canais habilitados aceitam o envio; se um falhar, ela é reenviada na próxima execução.

**Discord**: Configurações do canal → Integrações → Webhooks → *Novo webhook* → copiar URL para `DISCORD_WEBHOOK_URL`.

**Telegram**: crie um bot com o @BotFather (`TELEGRAM_BOT_TOKEN`), mande uma mensagem para ele e descubra seu `TELEGRAM_CHAT_ID` (por exemplo com o @userinfobot).

**Notion**: crie uma integração em <https://www.notion.so/my-integrations> (`NOTION_TOKEN`), crie um banco de dados com as propriedades abaixo (nomes exatos), compartilhe o banco com a integração e copie o ID dele da URL (`NOTION_DATABASE_ID`).

| Propriedade | Tipo |
|---|---|
| Name | Título |
| Company | Texto |
| Area | Seleção |
| Location | Texto |
| Source | Seleção |
| URL | URL |
| Published | Data |

---

## Agendamento

**Linux / macOS (cron)**, a cada 6 horas:

```cron
0 */6 * * * cd /caminho/remote-junior-jobs && .venv/bin/python -m jobcrawler run >> logs/cron.log 2>&1
```

**Windows (Agendador de Tarefas)**: crie uma tarefa que execute
`C:\caminho\remote-junior-jobs\.venv\Scripts\python.exe` com argumentos `-m jobcrawler run` e "Iniciar em" `C:\caminho\remote-junior-jobs`.

Não agende com intervalo menor que 1 hora: as APIs pedem isso, e o cache HTTP de 60 minutos já faria a segunda execução reaproveitar os dados.

---

## Tratamento de erros

| Situação | Comportamento |
|---|---|
| HTTP 429 (rate limit) e 5xx | retry com backoff exponencial + jitter, respeitando `Retry-After` |
| Queda de rede / timeout | até `max_retries` novas tentativas |
| 403, CAPTCHA, WAF, proxy recusando | **não insiste**: a fonte é pulada nesta execução (sem técnicas de evasão) |
| Falhas repetidas no mesmo host | *circuit breaker* desativa o host até a próxima execução |
| Mudança de formato da API / DOM | se mais da metade dos itens falhar no parse, registra "possível mudança de formato" com os campos recebidos |
| HTML no lugar de JSON | erro claro ("Resposta não é JSON") em vez de crash |
| Uma fonte quebra | as demais continuam; o resumo final lista os erros por fonte |
| Mesma vaga em várias fontes | deduplicada por título + empresa normalizados |

Requisições ao mesmo domínio são serializadas com intervalo mínimo (`min_interval_per_host_seconds`), mesmo com as fontes rodando em paralelo.

---

## Estrutura

```
remote-junior-jobs/
├── config.yaml              # fontes, filtros, notificações
├── .env.example             # credenciais (copie para .env)
├── requirements.txt
├── jobcrawler/
│   ├── cli.py               # comandos run / list / check
│   ├── pipeline.py          # coleta → dedupe → filtro → banco → export → notificação
│   ├── filters.py           # motor de filtragem (área, senioridade, região, anos)
│   ├── http.py              # cliente HTTP: retry, rate limit, circuit breaker, cache
│   ├── models.py            # modelo Job normalizado
│   ├── text.py              # HTML→texto, datas, fusos, normalização
│   ├── storage.py           # SQLite
│   ├── exporters.py         # HTML / CSV / JSON
│   ├── html_report.py       # relatório HTML (template + escape)
│   ├── notifiers.py         # Discord / Telegram / Notion
│   └── sources/             # um arquivo por fonte
└── tests/                   # 100 testes, rodam sem internet
```

## Adicionar uma fonte nova

1. Crie `jobcrawler/sources/minha_fonte.py` com uma função pura `parse_job(item) -> Job` e uma classe que herda de `Source` com `name = "minha_fonte"` e um método `fetch()` (use `self.http.get_json/get_text` e `self._safe(...)`).
2. Registre a classe em `jobcrawler/sources/__init__.py`.
3. Adicione `minha_fonte: {enabled: true, ...}` em `config.yaml`.
4. Escreva um teste do parser com um exemplo real da resposta.

## Testes

```bash
pytest -q
```

Os testes cobrem o filtro (blacklist, marcadores júnior, anos de experiência, regiões, modos smart/strict), os parsers de cada fonte com amostras no formato real, o cliente HTTP (429, 5xx, bloqueio, cache) e o pipeline ponta a ponta com uma fonte simulada.

---

## Observação sobre elegibilidade

Muitas vagas remotas restritas a US, Canadá ou Austrália exigem **autorização de trabalho no país** (cidadania, green card, visto), mesmo sendo remotas. Se você não tem essa autorização, as vagas marcadas como `GLOBAL` costumam ser as mais viáveis; a coluna "Regiões" do CSV permite filtrar por elas.
