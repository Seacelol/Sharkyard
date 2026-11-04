# Sharkyard: funcionalidades em detalhe

Como cada parte do app funciona, do ponto de vista de quem usa e de quem mantém. Para instalar e rodar, veja o [README](../README.md).

## Dados e contas

Tudo fica em `~/.mtg-collection` (ou na pasta da variável `MTG_DATA_DIR`):

- `data.db`: banco SQLite com usuários, coleções e decks. Junto com `custom-images/`, é o que precisa de backup.
- `custom-images/`: imagens enviadas (versões personalizadas e capas de deck).
- `secret.key`: chave que assina o cookie de sessão. Se apagar, todo mundo precisa entrar de novo.
- `sessions/`: sessões abertas nos navegadores. Não precisa de backup nem deve ser compartilhada.
- `cache/`: símbolos de coleção e `catalogo.db`, a cópia local das cartas do Scryfall. Pode apagar; é refeito.

Catálogo local: ao iniciar e depois a cada 6 horas, o servidor confere em `/bulk-data` se o Scryfall publicou um
arquivo "All Cards" novo (sai uma vez por dia, em geral por volta das 07:00 de Brasília, sem horário garantido).
Se publicou, baixa, monta um banco novo ao lado e troca pelo antigo de uma vez. Do arquivo, que traz todos os
idiomas, ficam as impressões em inglês e em português e as que só existem em outro idioma. Sugestões, cartas,
impressões e listas de texto passam a ser lidas daí; a busca com filtros e as cartas que ainda não estão na cópia
continuam indo à API. Enquanto a cópia não fica pronta, tudo funciona pela API. `MTG_CATALOG=0` desliga. No console
aparece "Catálogo do Scryfall atualizado: N cartas" a cada troca.

Impressões em português: aparecem na lista de edições da página da carta com a etiqueta PT, e a página mostra
nome, tipo e texto impressos em português, com o nome em inglês embaixo e o texto Oracle (inglês) recolhido, que é
o que vale nas regras. Na coleção e no deck, a carta continua com o nome em inglês (exportação e validação usam
ele) e ganha o selo PT.

Perfil (Minha conta): nome de exibição, bio de até 20 caracteres (aparece embaixo do nome no ranking) e ícone
redondo. No editor do ícone a pessoa arrasta a imagem e ajusta o zoom dentro do círculo; a imagem escolhida não sobe
para o servidor: o navegador recorta e envia só um PNG de 256 px. Sem ícone, aparece a inicial do nome numa cor fixa. O ícone aparece no topo, no
ranking e nos decks dos amigos.

O primeiro cadastro vira administrador. Os seguintes precisam do código de convite, que o admin vê em Minha conta.
Em Minha conta, o admin também cuida das contas dos amigos pelo menu de cada uma. "Gerar senha temporária" é para
quem esqueceu a senha (o app não tem e-mail): a senha antiga e as sessões abertas deixam de valer, e a pessoa entra
com a temporária e só passa da tela "Criar nova senha" depois de escolher a sua. "Desativar" bloqueia a entrada sem
apagar nada, e dá para reativar. "Apagar" remove a conta com coleção, pastas, decks, vitórias e imagens; pede para
digitar o nome de usuário antes. O admin não pode fazer nenhuma das três com a própria conta.
As senhas são guardadas só como hash argon2. Trocar a senha desconecta as sessões em outros navegadores (páginas
já abertas voltam para o login em até 10 segundos). Depois de 5 senhas erradas no mesmo usuário (ou 20 vindas do
mesmo endereço) em 15 minutos, o login fica bloqueado por 15 minutos.

O banco é criado e atualizado sozinho ao iniciar o app. Para mudar a estrutura, altere `database/tables.py` e gere
a migração com `alembic revision --autogenerate -m "descrição"`.

## Coleção

- Adicionar: pelo botão "Adicionar esta versão" na página da carta, ou pela busca em Minha coleção (adiciona a
  edição padrão). Adicionar de novo a mesma edição soma no lote simples (sem foil, proxy, preço ou observação).
- Editar: edição, quantidade, foil, proxy, preço pago por unidade (em reais, guardado em centavos) e observações.
  Proxies aparecem separados nos totais.
- Versão personalizada: criada na página da carta, com nome, código, autor, observações e imagem opcional.
  Só o dono vê, aparece no topo da coluna de versões e pode entrar na coleção como qualquer edição.
  Trocar a imagem atualiza todas as cópias na coleção e nos decks. Apagar a versão apaga as cópias da coleção,
  mas as linhas de deck que usavam ela voltam para a edição oficial (o aviso mostra quantas de cada).

- Pastas: cada item fica em no máximo uma pasta. Com uma pasta aberta, a carta adicionada pela busca entra nela.
  Apagar a pasta não apaga os itens (voltam para "Sem pasta"). "Selecionar" permite mover ou remover vários.

## Decks

Abrir um deck (/deck/<id>) mostra ele só para ver, com quatro jeitos de exibir as cartas: Lista (com edição e
custo), Texto (em colunas, como uma lista para copiar), Imagens (grade de cartas com a quantidade no canto) e Pilhas
(uma coluna por tipo, com as cartas empilhadas mostrando a faixa do nome). O modo escolhido fica lembrado no
navegador. Passando o mouse numa carta, ela aparece grande ao lado do cursor (à direita; à esquerda se não couber). O dono vê o botão Editar, que abre a montagem (/deck/<id>/edit) na versão que estava vendo; "Ver deck"
e Concluir voltam para a visualização. Amigos abrem a mesma página, sem o botão.

- Grade com capa (carta do deck ou imagem enviada), cores (identidade de cor somada das cartas, ordem WUBRG),
  formato e número de cartas. Sem capa, o fundo é um degradê com as cores do deck.
- Editar: nome, formato, pasta, observações, visível para os amigos e capa.
- "Gerenciar" marca vários decks para mover de pasta ou apagar. Apagar um deck não mexe na coleção.

Zona de comando: nos formatos com comandante, o diálogo do deck e o botão "Zona de comando" da montagem têm o
campo do comandante (a busca só sugere quem pode ser comandante no formato) e o do segundo comandante, que só
aparece quando a carta permite e só sugere pares válidos: Partner, Partner with, Partner—(grupo), Friends forever,
Choose a Background e Doctor's companion. O companheiro é opcional em qualquer formato e fica fora do deck (no
Commander não conta nas 100; nos outros ocupa vaga do sideboard). Com comandante, a busca da montagem sugere só
cartas da identidade de cor dele (dá para desligar) e as cores do deck passam a ser as do comandante.

Versões: cada deck tem uma ou mais versões, cada uma com a própria lista de cartas (inclusive comandante e
companheiro). O seletor "Versão" no topo da montagem troca de versão; o "+" cria uma nova como cópia da atual;
o menu ao lado renomeia ou apaga (a última não pode ser apagada). Nome, formato, capa, pasta e cartas
personalizadas do deck valem para todas. A versão aberta por último é a que aparece na grade de decks.

Estatísticas: aba ao lado de "Cartas" na montagem, sempre da versão aberta. Contam o principal e o comandante
(sideboard, companheiro e "talvez" ficam de fora): cartas, terrenos, valor de mana médio sem terrenos, curva de
mana (criaturas e outras mágicas), tipos, símbolos de mana coloridos nos custos, raridade, proxies, cartas
personalizadas, quanto foi pago, quantas faltam na coleção e o valor estimado em dólar pelo Scryfall. Também:
fontes de mana dos terrenos por cor (pelo texto do Scryfall: "Add ...", tipos básicos e terrenos que buscam
terreno), chance de cada quantidade de terrenos na mão de 7 e a chance de ter uma carta até um turno, começando
ou comprando (o comandante não entra no grimório).

Comparar versões: no menu da versão, mostra o que entrou, saiu e mudou de quantidade entre duas versões (por
carta, qualquer edição, e seção).

Validação: confere a condição de construção dos dez companheiros de Ikoria, aceita veículo e espaçonave lendária
como comandante no Brawl, e no Gladiator pede no mínimo 100 cartas, singleton e sem companheiro.

Lista e exportação: o principal aparece dividido por tipo (criaturas, planeswalkers, batalhas, instantâneas,
feitiços, artefatos, encantamentos, terrenos), cada carta em um grupo só (criatura artefato em criaturas, terreno
artefato em terrenos). O botão de exportar gera a versão aberta em texto simples, MTG Arena, Moxfield/Archidekt
(com *F* de foil), Magic Online (.txt), Cockatrice (.cod) ou planilha (.csv), para copiar ou baixar.

Decks dos amigos: "Dos amigos" em Meus decks lista os decks que outras pessoas marcaram como "Visível para os
amigos", com filtro por nome, pessoa e formato. O deck abre só para ver: cartas por tipo, estatísticas (o "faltam
na coleção" é da coleção de quem está vendo) e exportar. Quem vê escolhe a versão (começa na atual do dono) sem
mudar nada no deck do dono. Imagens de versões e cartas personalizadas usadas no deck também ficam visíveis.

Ranking: o botão de troféu na página do deck registra vitórias (data, versão e observação) e mostra o histórico.
Entram no ranking (/ranking) os decks visíveis para os amigos; há um ranking de decks e um de jogadores (soma
dos decks), com filtro de temporada (ou geral), formato e período. Empates dividem a posição. Cada vitória fica
na temporada aberta quando foi registrada. O admin abre e encerra temporadas, tira decks ou jogadores do ranking
sem apagar nada, corrige ou apaga vitórias de qualquer deck e pode zerar o ranking (de uma temporada ou tudo).

Observações do deck: ficam logo abaixo do nome; se passarem de três linhas, aparecem recolhidas com "... ver
mais" para abrir. Na grade de decks aparecem as duas primeiras linhas.

Montagem (clique no deck). Cada mudança é salva na hora.

- Adicionar na seção escolhida (principal, comandante, sideboard, talvez) pela busca, da coleção (leva edição,
  foil e proxy do item), por lista em texto ou criando uma carta personalizada. Na lista, cabeçalhos como
  "Sideboard" trocam a seção; linhas não reconhecidas voltam para a caixa para corrigir.
- Cada carta tem edição (inclusive versão personalizada, que dá para criar ali mesmo), quantidade, seção, foil,
  proxy, preço pago e observações. Marcas: "Personalizada" (edição personalizada) e "Carta personalizada".
- Carta personalizada criada no deck fica só nele, a não ser que seja guardada na coleção; aí serve para
  qualquer deck. Apagar o deck apaga as que só existiam nele.
- Concluir: revisão com todas as cartas (editar ou tirar) e os avisos do formato (tamanho, cópias, legalidade
  pelo Scryfall, sideboard, comandante e identidade de cor). Os avisos não impedem concluir. Depois pergunta se
  as cartas que faltam na coleção (por carta, qualquer edição, sem contar "talvez") devem entrar nela.

## Aparência

A página inicial (/) mostra o logo, a busca e atalhos (carta aleatória, busca avançada, coleção, decks); os
resultados ficam em /search (endereços antigos /?q=... continuam funcionando). "Buscar" no cabeçalho (a lupa, no
celular) abre o campo de busca ali mesmo, com sugestões, sem sair da página.

Ao lado do ícone da conta, no cabeçalho, uma chave sol/lua troca entre claro e escuro na hora. As outras opções
ficam em Aparência: no computador, uma janela no canto (uma só, sem empilhar) aberta pelo menu do usuário; no
celular e em Minha conta, a mesma seção na página. Lá estão a chave, o "Automático" (segue o claro/escuro do
aparelho) e os seis temas: Tubarão (padrão), Ilha, Planície, Pântano, Montanha e Floresta. Cada clique já mostra as
cores e fica salvo na conta. O fundo e as superfícies levam um pouco da cor do tema. As cores ficam em
`ui/theme.py`. Versões e cartas personalizadas usam o tubarão do logo como símbolo de edição, na cor do tema.

Limites de tamanho (em `config.py`): nome de exibição e bio 20 caracteres, pasta 30, deck 40, versão 30,
temporada 40, versão personalizada 40, carta personalizada 60. O campo não deixa passar e mostra o contador.

Instalar como app: no Chrome ou Edge, o ícone de instalar na barra de endereço (ou menu > Instalar); no Android,
menu > Adicionar à tela inicial; no iPhone, Compartilhar > Adicionar à Tela de Início. Precisa de HTTPS (o túnel da
Cloudflare resolve) ou do endereço localhost. Os ícones estão em `ui/static/`, gerados a partir do logo.
Na janela desktop (sem --web) o ícone da janela e da barra de tarefas é `ui/static/icon.ico`; no Windows isso
exige o pywebview 6 ou mais novo.

No celular (telas menores que 640px) o cabeçalho fica com o logo, a lupa e a conta, e as páginas ficam numa barra
embaixo (Início, Avançada, Coleção, Decks, Ranking), como num app. A busca e os decks mostram dois por linha, e
listas e diálogos se reorganizam para caber na largura. O cabeçalho se recolhe ao rolar para baixo e volta ao rolar
um pouco para cima.
