# Sharkyard: arquitetura

A regra é que as dependências só descem: `ui` usa `services` e `models`, `services` usa `models`, e `models` não importa nada do projeto. A interface nunca vê o JSON do Scryfall.

## Estrutura dos arquivos

```
main.py                         entrada: lê --web/--port/--host, liga o catálogo e sobe o app
sharkyard.bat, tunel.bat        atalhos do Windows: subir o app e o túnel rápido da Cloudflare
mtg_collection/
  config.py                     constantes (nome, porta, Scryfall, pasta de dados)
  models.py                     modelos de domínio (Card, CollectionEntry, CustomPrint, Deck, Folder, User...)
  database/                     banco SQLite: conexão (__init__), tabelas (tables.py) e migrações Alembic
  services/
    scryfall.py                 cliente da API: conexão reaproveitada, limite de requisições,
                                conversão do JSON para os modelos
    catalog.py                  cópia local do Scryfall (arquivo diário "All Cards", inglês e português) em SQLite
    search_query.py             monta a consulta na sintaxe do Scryfall a partir dos filtros
    accounts.py                 contas: cadastro, login, senha, perfil, convite e administração
    collection.py               coleção (adicionar, editar, mover, totais) e versões personalizadas
    folders.py                  pastas da coleção e dos decks
    decks.py                    decks (criar, editar, apagar vários, mover, capa, cores), cartas do deck e
                                o que falta na coleção
    decklist.py                 lê listas em texto ("4 Bolt", "4x Bolt", formatos do Arena/Moxfield/MTGO)
    deck_validation.py          confere o deck no formato (tamanho, cópias, legalidade, comandante)
    custom_cards.py             cartas personalizadas (que não existem no Magic)
    commander.py                zona de comando: quem pode ser comandante, pares de parceiros, companheiro
    companion.py                condições de construção dos dez companheiros
    ranking.py                  vitórias, temporadas e rankings de decks e jogadores
    login_throttle.py           limite de tentativas de login por usuário e por endereço
    deck_stats.py               estatísticas do deck (curva, tipos, símbolos de mana, raridade, pago,
                                fontes de mana dos terrenos, probabilidades) e grupos por tipo da lista
    deck_export.py              exportação: texto, MTG Arena, Moxfield/Archidekt, MTGO, Cockatrice, CSV
  ui/
    layout.py                   moldura comum (cabeçalho, menu e menu do usuário); NAV_ITEMS define o menu
    auth.py                     sessão do usuário e middleware que exige login
    routes.py                   caminhos das páginas (search_path, card_path)
    set_icons.py                rota /set-icon/<código>.svg: símbolos de coleção servidos do cache local
    theme.py                    temas (cores) e modo claro/escuro; escolha da aparência
    assets.py                   arquivos fixos (/static), manifesto e service worker para instalar como app
    static/                     logo, tubarão (símbolo de edição personalizada), ícones do app e favicon
    custom_images.py            imagens enviadas: versões personalizadas (só o dono) e capas de deck
                                (dono, ou amigos se o deck estiver visível)
    printings.py                impressões de uma carta para o usuário (oficiais + personalizadas)
    formatting.py               formatação para exibição (preços, símbolos de mana, legalidade)
    components/                 peças reutilizáveis (controls.py: botão de voltar, seletor e imagem padronizados): busca com sugestões, seletor de tipos, barra de pastas,
                                seleção múltipla, escolha de imagem e diálogos (item, versão, deck)
    pages/                      uma página por módulo, registrada em pages/__init__.py
      login.py                  entrar (/login), criar conta (/register) e nova senha (/new-password)
      account.py                minha conta (/account): perfil, senha, convite e contas (admin)
      collection.py             minha coleção (/collection): adicionar pela busca, pastas, filtros, totais,
                                edição e seleção múltipla
      decks.py                  meus decks (/decks): grade com capa, cores e formato, pastas, gerenciar
      deck_builder.py           montagem do deck: adicionar, editar, revisar e concluir
      ranking.py                ranking (/ranking): decks e jogadores, filtros e ferramentas do admin
      deck_view.py              decks dos amigos (/decks/friends), ver um deck (/deck/<id>, com os modos de
                                exibição) e a rota da montagem (/deck/<id>/edit, só o dono)
      home.py                   página inicial (/): logo, busca e atalhos
      search.py                 resultados da busca (/search?q=...)
      advanced.py               busca avançada (/advanced): formulário que gera a consulta e abre a busca;
                                guarda os campos para voltar dos resultados com tudo preenchido
      card.py                   página da carta (/card/<id> ou /card/custom-<n>): versões na lateral,
                                quadro "Na sua coleção", texto, preços, legalidade e rulings
tests/                          testes do serviço e da interface, sem acessar a internet
```

## Adicionar uma página

1. Crie `mtg_collection/ui/pages/<nome>.py` com uma função decorada com `@ui.page("/rota")` usando `with frame("Título"):`.
2. Importe o módulo em `mtg_collection/ui/pages/__init__.py`.
3. Adicione a entrada em `NAV_ITEMS` no `layout.py`.

Lógica que não é de tela (acesso a banco, cálculos da coleção) vai em `services/`, com teste próprio em `tests/`.

## Decisões que valem saber

- **Uma consulta por operação, não por item:** mover, apagar, copiar versão e adicionar várias cartas usam leitura
  e gravação em lote (`IN (...)`, `insert` com lista). Consultas dentro de laço que crescem com os dados são bug.
- **Nada pesado no loop do servidor:** hash de senha, catálogo local e gravação de imagens rodam em thread
  (`run.io_bound`/`asyncio.to_thread`). O servidor atende todos os usuários num loop só.
- **Permissão sempre no serviço:** cada função recebe o `user_id` e confere o dono (ou a visibilidade para amigos).
  A interface esconder um botão não é proteção.
- **Migrações sem cascata:** as chaves estrangeiras ficam desligadas durante as migrações (o SQLite apagaria em
  cascata ao recriar uma tabela pai) e são conferidas com `PRAGMA foreign_key_check` no fim.
- **Modo escuro já no HTML:** `theme.py` faz o HTML de cada pessoa sair com o modo dela, para a página não piscar
  clara antes de ficar escura.
