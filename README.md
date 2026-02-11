Web Scrapper VIP Commerce
==========================

Pequeno scrapper para baixar imagens de produtos do portal VIP Commerce usando a API Urbanic.

Este repositório contém um script que baixa imagens de produtos diretamente da API de integração da Urbanic. **Não requer Selenium, Chrome ou interface gráfica** — funciona puramente com requisições HTTP.

Índice
------

- **Método Novo (Recomendado)**: API-based downloader
- Método Antigo (Legado): Selenium-based scraper
- Como rodar
- Configuração

---

## 🚀 Método Novo (Recomendado): API-based Downloader

**Vantagens:**
- ✅ Muito mais rápido (sem overhead de navegador)
- ✅ Roda em qualquer VM (sem necessidade de GUI/Chrome)
- ✅ Dependências mínimas (apenas requests, tqdm, urllib3)
- ✅ Mais confiável (dados diretos da API)

### Requisitos

Apenas Python 3.7+ e as dependências mínimas:

```bash
pip install -r requirements-minimal.txt
```

### Como rodar

```bash
python3 -m src.download_images_api
```

O script:
1. Busca todos os produtos da API Urbanic (com paginação automática)
2. Extrai as URLs das imagens (preferência por tamanho 250px, senão a maior disponível)
3. Baixa em paralelo (8 workers) para `src/assets/raw_images/`
4. Nomeia cada imagem pelo `codigo_erp.jpg`

### Configuração

Edite as constantes no topo de `src/download_images_api.py`:
- `PREFERRED_IMAGE_SIZE = 250` — tamanho preferido (250, 500, 144, 60)
- `MAX_WORKERS = 8` — número de downloads paralelos
- `API_ENDPOINT` — URL da API (já configurado)

---

## 📦 Método Antigo (Legado): Selenium-based Scraper

**⚠️ Apenas para referência.** Use o método API acima, que é muito superior.

### Requisitos (bibliotecas do sistema)

O Chrome headless (ou a build do Chromium) com o chromedriver precisa das bibliotecas abaixo em sistemas Debian/Ubuntu. Execute como root/ sudo:

```
sudo apt-get update && sudo apt-get install -y \
    libglib2.0-0t64 \
    libnss3 \
    libfontconfig1 \
    libx11-6 \
    libx11-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libxtst6 \
    libasound2t64 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libcups2t64 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0t64 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libxfixes3 \
    libxrandr2 \
    libxss1 \
    at-spi2-core
```

Observação: nomes das bibliotecas podem variar entre distribuições/versões — use o package manager da sua distro quando necessário.

### Estrutura de assets (Selenium legado)

O projeto espera encontrar os binários do Chrome/Chromium e do Chromedriver dentro da pasta `src/assets` (já organizada no repo). A estrutura deve ser:

- `src/assets/chrome-linux64/chrome` — executável do Chrome/Chromium (marcar como executável)
- `src/assets/chromedriver-linux64/chromedriver` — binário do chromedriver compatível (marcar como executável)
- `src/assets/data/product_map.json` — mapa de produtos (chave: product_id, valor: codigo_erp)
- `src/assets/raw_images/` — pasta onde as imagens baixadas serão salvas (criada automaticamente)

Certifique-se de que os binários têm permissão de execução:

```
chmod +x src/assets/chrome-linux64/chrome src/assets/chromedriver-linux64/chromedriver
```

### Como rodar (Selenium legado)

```bash
pip install -r requirements.txt
python3 -m src.download_images
```

---

## 📝 Notas

O código carrega algumas constantes de `src/utils/config.py`. O mais importante é o `DOMAIN_KEY` (o domínio base do site). Você pode configurá-lo de duas formas:

1) Usando um arquivo `.env` na raiz do projeto (recomendado):

```
# .env (exemplo)
DOMAIN_KEY=supervillesupermercado.com.br
# AUTH_TOKEN=...
# API_BASE_URL=...
```

## 📊 Performance

Resultados típicos (~9000 produtos):
- **Método API**: ~2-5 minutos (depende da banda e workers)
- **Método Selenium (legado)**: ~30-60 minutos