# Jobs: crawler de vagas júnior em Segurança, DevOps e Infra

Busca vagas **júnior** em três áreas, filtra com regras rígidas e gera um relatório HTML com busca e filtros.

| Área | Exemplos de cargos aceitos |
|---|---|
| Cibersegurança | Analista de Segurança da Informação Júnior, Analista de SOC Jr, Analista de Gestão de Vulnerabilidades Júnior |
| DevOps / SRE / Plataforma | Engenheiro DevOps Júnior, SRE Jr, Analista de Observabilidade Júnior |
| Infra / Cloud / Suporte | Analista de Infraestrutura Jr, Analista de Redes Júnior, Analista de Suporte N1, Analista de Infraestrutura I |

O projeto tem dois perfis de busca, cada um num arquivo de configuração:

| Perfil | Arquivo | O que procura |
|---|---|---|
| **Rio (padrão)** | `config.yaml` | Vagas **híbridas** no **Rio de Janeiro** e região metropolitana |
| Remoto | `config.remoto.yaml` | Vagas **100% remotas** em EUA, Canadá, Austrália e globais |

---

## Instalação

Requer **Python 3.10+**.

```bash
git clone https://github.com/GalakCV/Jobs.git
cd Jobs
python -m venv .venv

# Linux / macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
cp .env.example .env        # opcional (Windows: copy .env.example .env)
```

---

## Uso

```bash
# Busca vagas híbridas no Rio e abre o relatório no navegador
python -m jobcrawler run --open

# Mesmo processo para o perfil de vagas remotas
python -m jobcrawler -c config.remoto.yaml run --open

# Relatório com o histórico do banco (sem acessar a rede)
python -m jobcrawler report --days 14 --open

# Gera também output/rejections.csv com o MOTIVO de cada vaga descartada
python -m jobcrawler run --explain

# Testar sem gravar no banco nem notificar
python -m jobcrawler run --dry-run

# Só algumas fontes
python -m jobcrawler run --sources gupy

# Repetir a cada 6 horas (Ctrl+C para sair)
python -m jobcrawler run --loop-hours 6

# Ver vagas encontradas nos últimos 3 dias
python -m jobcrawler list --days 3

# Importar vagas de um JSON para o banco (passam pelo filtro)
python -m jobcrawler import vagas.json

# Testar o filtro com um título, sem acessar a rede
python -m jobcrawler check "Analista de SOC Júnior" --location "Niterói, RJ" --workplace hybrid
python -m jobcrawler check "Analista de Infraestrutura Jr" --location "Rio de Janeiro" --description-file descricao.txt

# Log detalhado: mostra a decisão do filtro para cada vaga
python -m jobcrawler -v run
```

Códigos de saída de `run`: `0` sucesso, `1` erro de configuração/arquivo, `2` **todas** as fontes falharam (útil para alertas no cron).

---

## Fontes do perfil Rio

| Fonte | Tipo | Observação |
|---|---|---|
| [Gupy](https://portal.gupy.io) | API JSON pública do portal | principal ATS do Brasil; informa cidade, estado e **modalidade** (`hybrid`, `remote`, `on-site`) em campo próprio |
| GitHub ([backend-br/vagas](https://github.com/backend-br/vagas)) | API de issues | labels de modalidade e nível (`Híbrido`, `Júnior`, `Estagiário`...); configure outros repositórios em `sources.github_issues.repos` |
| LinkedIn | HTML (busca de visitante) | **desligado por padrão**, veja abaixo |

Cada vaga salva mantém o link original da fonte.

- **Gupy**: a busca é por termo (`queries` no config) em todo o Brasil, e a filtragem por cidade e modalidade é feita localmente. Vagas de estágio, trainee, jovem aprendiz e banco de talentos são descartadas pelo tipo da vaga.
- **GitHub**: sem token, a API permite 60 requisições por hora. Para mais, crie um token sem permissões em <https://github.com/settings/tokens> e coloque em `GITHUB_TOKEN` no `.env`.
- **LinkedIn**: os Termos de Uso proíbem coleta automatizada, o site responde HTTP 429 depois de poucas consultas, e o filtro de modalidade da busca **erra com frequência**. Se ligar (`sources.linkedin.enabled: true`), use em volume baixo e por sua conta e risco. As vagas vêm com aviso "confira na vaga". Ao primeiro bloqueio a fonte é pulada; o código não tenta contornar.

**Fora do escopo, e por quê:** Indeed, Catho, InfoJobs e Vagas.com não têm API pública e usam proteção anti-bot. Um scraper ali quebraria toda semana e exigiria técnicas de evasão que este projeto não usa. Para adicionar uma fonte, veja *Adicionar uma fonte nova*.

As fontes do perfil remoto (Himalayas, Jobicy, Remotive, Remote OK, We Work Remotely) estão descritas no `config.remoto.yaml`.

---

## Saídas

| Arquivo | Conteúdo |
|---|---|
| `output/jobs_latest.html` | **relatório visual** da última execução (abra no navegador) |
| `output/report.html` | gerado por `report`: histórico do banco dos últimos N dias |
| `output/jobs_latest.csv` | vagas aceitas na última execução (abre direto no Excel/Sheets, com acentos) |
| `output/jobs_latest.json` | o mesmo, em JSON |
| `output/jobs_AAAAMMDD-HHMMSS.*` | cópia datada de cada execução |
| `output/rejections.csv` | com `--explain`: etapa e motivo de cada descarte |
| `data/jobs.db` | SQLite com o histórico (o perfil remoto usa `data/jobs_remoto.db` e `output/remoto/`) |
| `logs/crawler.log` | log rotacionado (5 arquivos de 1 MB) |

### Relatório HTML

Um único arquivo, sem dependências, que abre em qualquer navegador (inclusive no celular):

- Barra colorida com a proporção de vagas por área; clique num segmento para filtrar.
- Filtro por **cidade** (Rio de Janeiro, Niterói, Duque de Caxias...), busca por cargo/empresa/tecnologia e "Só novas".
- Cada vaga mostra empresa, **modalidade**, cidade, por que foi considerada júnior, data relativa e um trecho da descrição.
- **Aviso amarelo** quando algo precisa ser conferido: modalidade não informada, cidade não informada ou modalidade vinda só do filtro de busca do LinkedIn.
- "Detalhes da execução" no rodapé: quantas vagas cada fonte trouxe, erros e por que as outras foram descartadas.
- Modo escuro automático. Todo texto vindo das fontes é escapado, e só links `http(s)` ficam clicáveis.

Título, escopo e rodapé do relatório ficam na seção `report` do config.

---

## Como o filtro funciona

Tudo é configurável em `config.yaml`. O texto é normalizado antes da comparação (minúsculo e sem acentos), então `Sênior`, `Senior` e `SÊNIOR` são a mesma coisa. Os termos usam limites de palavra: `sr` **não** casa com `SRE` e `pl` **não** casa com `PL/SQL`.

Ordem das verificações (a primeira reprovação encerra):

1. **Idade**: descarta vagas com mais de `max_age_days` (padrão 30).
2. **Modalidade** (`workplace_types`, padrão `[hybrid]`). A modalidade vem, nesta ordem de confiança:
   1. do campo da fonte (Gupy, labels do GitHub);
   2. de palavras no título, local ou labels ("Híbrido", "Presencial", "Remoto");
   3. de frases de regime de trabalho na descrição ("modelo híbrido", "3x por semana no escritório"). "Nuvem híbrida" e "acesso remoto" não contam;
   4. do filtro de busca do LinkedIn (só indício, gera aviso).

   Vaga sem modalidade informada entra com aviso (`unknown_workplace: keep`) ou é descartada (`reject`).
3. **Área** (whitelist no título). Exclui falsos positivos comuns no Brasil: "Segurança **do Trabalho**", "Segurança **Patrimonial**", "**Redes Sociais**", "Infraestrutura **Civil**", vagas comerciais.
4. **Blacklist de senioridade no título** (regra crítica): estágio, trainee, aprendiz, pleno, PL, sênior, sr, especialista, II/III, N2/N3, coordenador, supervisor, gerente, líder, arquiteto, entre outros. "Júnior/Pleno" também é descartada.
5. **Nível declarado pela fonte**: tipo de vaga do Gupy (estágio, trainee, banco de talentos) e labels do GitHub (Pleno, Sênior, Estagiário).
6. **Descrição**: frases de nível ("vaga para pleno") e anos de experiência, em português e inglês ("experiência mínima de 3 anos", "3+ years"). Com `max_years_experience: 2`, exigir **3+ anos** descarta.
7. **Júnior explícito**: precisa de um marcador no título (júnior, jr, assistente, N1, nível 1, "Analista de Infraestrutura **I**") ou do nível informado pela fonte.
8. **Localização** (modo `cities`):
   - cidade-alvo ou um bairro dela ("Barra da Tijuca, Rio de Janeiro" conta como Rio);
   - cidades da região metropolitana, se `include_metro: true` (Niterói, São Gonçalo, Duque de Caxias...);
   - "Volta Redonda, Rio de Janeiro" **não** conta: aí "Rio de Janeiro" é o estado;
   - só o estado ("[RJ]") entra com aviso "confira a cidade" (`accept_state_only`).

### Ajustes comuns

| Quero... | Mude no `config.yaml` |
|---|---|
| Incluir vagas presenciais também | `workplace_types: [hybrid, onsite]` |
| Incluir remotas abertas a quem mora no Rio | `workplace_types: [hybrid, remote]` |
| Só a capital, sem região metropolitana | `include_metro: false` |
| Ver vagas sem nível no título ("Analista de Infraestrutura") | `require_junior_marker: false` (entram com aviso; a blacklist continua valendo) |
| Descartar vagas sem modalidade informada | `unknown_workplace: reject` |
| Incluir help desk / service desk | descomente as linhas no fim de `filters.areas.infra_cloud_sysadmin` |
| Aceitar até 3 anos de experiência | `max_years_experience: 3` |
| Buscar outra cidade | troque `target_cities`, `metro_cities` e `target_state` |

Termo com `: ` (dois-pontos e espaço) no YAML precisa de aspas, senão vira dicionário. O programa avisa se isso acontecer.

### Descrição: modo `smart` (padrão) vs `strict`

Aplicar a blacklist **em qualquer lugar da descrição** elimina quase todas as vagas júnior, porque descrições trazem frases como *"reportando ao **gerente**"* ou *"apoio aos analistas **sêniores**"*. Por isso há dois modos:

- **`smart`** (padrão): descarta por frases que descrevem o nível da própria vaga e por anos de experiência.
- **`strict`**: descarta se **qualquer** termo da blacklist aparecer na descrição. Espere pouquíssimos resultados.

Rode com `--explain` e confira o `rejections.csv` para calibrar.

---

## Notificações (opcional)

Habilite em `config.yaml` → `notifications` e preencha o `.env`. Só vagas **novas** são enviadas, no máximo `max_per_run` por execução. Uma vaga só é marcada como notificada quando todos os canais habilitados aceitam o envio.

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
0 */6 * * * cd /caminho/Jobs && .venv/bin/python -m jobcrawler run >> logs/cron.log 2>&1
```

**Windows (Agendador de Tarefas)**: crie uma tarefa que execute
`C:\caminho\Jobs\.venv\Scripts\python.exe` com argumentos `-m jobcrawler run` e "Iniciar em" `C:\caminho\Jobs`.

Não agende com intervalo menor que 1 hora: o cache HTTP de 60 minutos faria a segunda execução reaproveitar os dados.

---

## Tratamento de erros

| Situação | Comportamento |
|---|---|
| HTTP 429 (rate limit) e 5xx | retry com backoff exponencial + jitter, respeitando `Retry-After` |
| Limite da API do GitHub | fonte pulada com mensagem pedindo `GITHUB_TOKEN` |
| Queda de rede / timeout | até `max_retries` novas tentativas |
| 403, CAPTCHA, WAF, proxy recusando | **não insiste**: a fonte é pulada nesta execução (sem técnicas de evasão) |
| Falhas repetidas no mesmo host | *circuit breaker* desativa o host até a próxima execução |
| Mudança de formato da API / DOM | se mais da metade dos itens falhar no parse, registra "possível mudança de formato" com os campos recebidos |
| HTML no lugar de JSON | erro claro ("Resposta não é JSON") em vez de crash |
| Uma fonte quebra | as demais continuam; o resumo final lista os erros por fonte |
| Mesma vaga em várias fontes | deduplicada por título + empresa normalizados |
| Banco criado por versão antiga | colunas novas adicionadas automaticamente |

---

## Estrutura

```
Jobs/
├── config.yaml              # perfil Rio (padrão): fontes, filtros, relatório, notificações
├── config.remoto.yaml       # perfil remoto internacional
├── .env.example             # credenciais (copie para .env)
├── requirements.txt
├── jobcrawler/
│   ├── cli.py               # comandos run / report / import / list / check
│   ├── pipeline.py          # coleta → dedupe → filtro → banco → export → notificação
│   ├── filters.py           # área, senioridade, modalidade, cidade, anos de experiência
│   ├── http.py              # cliente HTTP: retry, rate limit, circuit breaker, cache
│   ├── models.py            # modelo Job normalizado
│   ├── text.py              # HTML→texto, datas, normalização
│   ├── storage.py           # SQLite (com migração automática)
│   ├── exporters.py         # HTML / CSV / JSON
│   ├── html_report.py       # relatório HTML (template + escape)
│   ├── notifiers.py         # Discord / Telegram / Notion
│   └── sources/             # gupy, github_issues, linkedin + fontes remotas
└── tests/                   # 200+ testes, rodam sem internet
```

## Adicionar uma fonte nova

1. Crie `jobcrawler/sources/minha_fonte.py` com uma função pura `parse_job(item) -> Job` e uma classe que herda de `Source` com `name = "minha_fonte"` e um método `fetch()` (use `self.http.get_json/get_text` e `self._safe(...)`). Se a fonte informa a modalidade num campo, preencha `Job.workplace` (`hybrid`, `onsite` ou `remote`).
2. Registre a classe em `jobcrawler/sources/__init__.py`.
3. Adicione `minha_fonte: {enabled: true, ...}` em `config.yaml`.
4. Escreva um teste do parser com um exemplo real da resposta.

## Testes

```bash
pytest -q
```

Os testes cobrem os dois perfis de filtro (blacklist em português e inglês, marcadores júnior, modalidade, cidades e região metropolitana, anos de experiência), os parsers de cada fonte com amostras no formato real, o cliente HTTP (429, 5xx, bloqueio, cache), a migração do banco e o pipeline ponta a ponta com uma fonte simulada.
