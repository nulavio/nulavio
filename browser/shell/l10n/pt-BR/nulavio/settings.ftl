# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

## Nulavio's panes and groups inside the engine's settings page (ADR 0008).

nulavio-read-failed =
    .message = Não foi possível ler esta opção agora. Recarregue a página para tentar de novo.

## Aparência

nulavio-layout-group =
    .label = Abas e organização da janela
    .description = Onde ficam as abas nas janelas deste perfil. A barra de endereço e os sinais de segurança continuam visíveis em qualquer organização; só o modo Imersivo, abaixo, os tira de vista.
nulavio-layout-lateral =
    .label = Lateral
    .description = Abas na lateral, sempre com os nomes.
nulavio-layout-top =
    .label = Abas no topo
    .description = Abas no alto, como na maioria dos navegadores.
nulavio-layout-focus =
    .label = Foco
    .description = Uma faixa fina na lateral, que abre quando o ponteiro chega nela.

nulavio-immersive =
    .label = Imersivo
    .description = Tira de vista a barra de endereço e as abas; a faixa do topo continua mostrando o perfil e o site. Elas voltam com o ponteiro na borda da janela, com o teclado, e sozinhas sempre que o navegador precisa mostrar algo.

nulavio-hide-page-title =
    .label = Esconder o título da página na barra da janela
    .description = A barra da janela, a barra de tarefas, o Alt+Tab e quem escolhe uma janela para compartilhar a tela veem só "Nulavio" e o nome do perfil, nunca a página. Isso não esconde os títulos nas abas, dentro da janela, nem a página em si.

nulavio-load-line =
    .label = Mostrar uma linha de carregamento no topo da página
    .description = Uma linha fina no topo da página enquanto ela carrega. Ela não diz quanto já carregou; a aba mostra o sinal de carregamento do próprio navegador de qualquer jeito.

nulavio-look-group =
    .label = Cores do Nulavio
    .description = Só a aparência das janelas e páginas do Nulavio. Nada aqui muda uma proteção.
nulavio-accent =
    .label = Cor de destaque
nulavio-accent-mint =
    .label = Menta (padrão)
nulavio-accent-blue =
    .label = Azul
nulavio-more-contrast =
    .label = Mais contraste
    .description = Textos e bordas mais fortes nas janelas e páginas do Nulavio. Para os sites, use Contraste em Acessibilidade.
nulavio-newtab-ambience =
    .label = Fundo suave na nova aba
    .description = Um fundo colorido atrás dos cartões da nova aba. Nunca em janelas privativas.
nulavio-reduce-transparency =
    .label = Reduzir transparência
    .description = Deixa sólidos os cartões da nova aba.
# #79, ADR 0018: what sites are told of the system's accessibility settings.
nulavio-share-accessibility =
    .label = Deixar os sites verem minhas preferências de movimento e contraste
    .description = Desligado, os sites não ficam sabendo que o seu sistema pede menos movimento ou mais contraste, porque isso ajuda a reconhecer você de um site para outro; as páginas também rolam com suavidade. Ligue se animações incomodarem você. As páginas do próprio Nulavio seguem o seu sistema nos dois casos.
# The same two switches when they cannot change anything, with the reason in place of the description.
nulavio-more-contrast-system =
    .label = Mais contraste
    .description = O seu sistema já pede alto contraste, e o Nulavio usa as cores dele.
nulavio-reduce-transparency-idle =
    .label = Reduzir transparência
    .description = Nada está transparente agora: o fundo suave está desligado.
nulavio-reduce-transparency-system =
    .label = Reduzir transparência
    .description = O seu sistema já pede menos transparência, então os cartões já ficam sólidos.
nulavio-reduce-transparency-contrast =
    .label = Reduzir transparência
    .description = “Mais contraste” já deixa os cartões sólidos.
nulavio-look-locked =
    .message = Algumas destas opções são gerenciadas pelo administrador.
nulavio-density-locked =
    .message = A densidade foi definida pelo administrador e não pode ser mudada aqui.

## Geral (the engine's first pane, while accounts are turned off)

nulavio-pane-general =
    .heading = Geral
nulavio-pane-general-nav = Geral

## Perfis e proteção

nulavio-pane-profiles =
    .heading = Perfis e proteção
nulavio-pane-profiles-nav = Perfis e proteção
nulavio-here-group =
    .label = Você está em
    .description = O perfil desta janela e como ele está protegido agora.
# $name is the profile's name, chosen by the person.
nulavio-here-plain =
    .label = { $name }
    .description = Sem senha. O Nulavio não criptografa os dados deste perfil.
nulavio-here-protected =
    .label = { $name }
    .description = Protegido e desbloqueado. Fica criptografado no disco enquanto está bloqueado.
nulavio-here-temporary =
    .label = { $name }
    .description = Temporário. Apagado ao fechar.
nulavio-here-unknown =
    .label = { $name }
    .description = Não foi possível ler a proteção deste perfil.
nulavio-here-none =
    .label = Perfil padrão
    .description = Esta janela foi aberta fora do grupo de perfis do Nulavio.
# One row per profile of the group. $name is the profile's name, chosen by the person; $here is "yes" for the
# profile of this window; $kind is "sensitive" for a profile made to clear itself every time it closes.
nulavio-profile-plain =
    .label = { $name }
    .description =
        { $here ->
            [yes] Este perfil. Sem senha.
           *[no] Sem senha.
        }{ $kind ->
            [sensitive] { " " }Sites sensíveis: cookies, dados de sites, histórico e cache são apagados sempre que ele fecha.
           *[other] { "" }
        }
nulavio-profile-unlocked =
    .label = { $name }
    .description =
        { $here ->
            [yes] Este perfil. Protegido e desbloqueado: volta a bloquear quando você fechar a última janela dele.
           *[no] Protegido. Desbloqueado agora: volta a bloquear quando você fechar a última janela dele.
        }{ $kind ->
            [sensitive] { " " }Sites sensíveis: cookies, dados de sites, histórico e cache são apagados sempre que ele fecha.
           *[other] { "" }
        }
nulavio-profile-locked =
    .label = { $name }
    .description = Protegido e bloqueado: criptografado no disco.
nulavio-profile-unknown =
    .label = { $name }
    .description = Não foi possível ler a proteção deste perfil.
nulavio-profile-temporary =
    .label = Perfil temporário
    .description = Temporário. Apagado ao fechar.
nulavio-profiles-group =
    .label = Seus perfis
    .description = Cada perfil guarda seus próprios logins, histórico e extensões. Um perfil protegido fica criptografado no disco enquanto está bloqueado.
nulavio-routing-group =
    .label = Qual site abre em qual perfil
    .description = Links de outros aplicativos e endereços digitados seguem estas regras e abrem direto no perfil certo, antes de qualquer carregamento. As regras ficam neste computador e só você as cria. Uma janela de login fica com o site que a abriu: com uma conta guardada num perfil (o Google, por exemplo), "Entrar com" essa conta num site de outro perfil pede um login lá também, e uma regra para o site de um buscador também manda para lá as pesquisas feitas com ele em outro perfil.

## Privacidade e segurança

nulavio-protections-group =
    .label = Proteções do Nulavio
    .description = O que o Nulavio acrescenta às proteções do navegador.
nulavio-filter-lists =
    .label = O que o uBlock Origin bloqueia
    .description = Anúncios, rastreadores e avisos de cookies: o que some de cada site depende das listas ligadas nele. Abra para ver ou mudar.
nulavio-filter-lists-cookies-on =
    .label = O que o uBlock Origin bloqueia
    .description = Avisos de cookies: uma lista que os esconde está ligada no uBlock Origin. Anúncios e rastreadores dependem das outras listas dele. Abra para ver ou mudar.
nulavio-filter-lists-cookies-none =
    .label = O que o uBlock Origin bloqueia
    .description = Avisos de cookies: nenhuma lista que os esconde está ligada no uBlock Origin. Abra as listas dele para ligar uma.
nulavio-filter-lists-off =
    .label = O uBlock Origin não está ligado neste perfil
    .description = As listas dele, que bloqueiam anúncios e escondem avisos de cookies, não estão em uso. Abra Extensões e temas para ligar.
nulavio-exceptions-group =
    .label = Exceções de sites
    .description = Sites em que uma proteção está desligada ou relaxada, por você ou pelo próprio navegador. Remova uma exceção e a proteção volta a valer para aquele site.
# $count is the number of changes waiting for a decision.
nulavio-guard-review =
    .label = Mudanças feitas fora do Nulavio
    .description =
        { $count ->
            [0] Nada para rever.
            [one] 1 mudança para rever.
           *[other] { $count } mudanças para rever.
        }
nulavio-guard-review-unwatched =
    .label = Mudanças feitas fora do Nulavio
    .description = O Guard não vigia este perfil: ele é temporário ou é a Área de IA de um agente.

## Privacidade e segurança: DNS (inside the engine's own DNS group)

nulavio-dns-group =
    .label = DNS: quem responde quando você procura um site
    .description = Para abrir um site, o navegador pergunta o endereço dele a um serviço de nomes (DNS). Quem responde vê quais sites você procura. O Nulavio não recebe nada em nenhum caso.

## Senhas

nulavio-passwords-group =
    .label = Quem guarda suas senhas
    .description = Um gerenciador por perfil. O Nulavio nunca lê o seu cofre. Com uma extensão, os pedidos de salvar e preencher do próprio navegador são desligados, para que só um gerenciador ofereça o preenchimento.
nulavio-passwords-now-none =
    .label = O gerenciador do navegador está desligado
    .description = Nenhum dos gerenciadores que o Nulavio conhece está ligado. Outra extensão pode estar cuidando das senhas.
nulavio-confirmed-group =
    .label = Sites parecidos que você confirmou
    .description = Você escolheu continuar nestes sites, mesmo parecidos com um site onde você tem login salvo, então o Nulavio não avisa sobre eles neste perfil. Remova um para o aviso voltar.

## Pesquisa

nulavio-translate-group =
    .label = Serviços de tradução na web
    .description = A tradução do próprio navegador, acima, acontece no seu computador e continua sendo a padrão. Um serviço na web só é usado depois que você o adiciona, e só num clique no item do menu que tem o nome dele. As extensões dos próprios serviços não vêm com o Nulavio; se preferir uma, instale-a em addons.mozilla.org.
nulavio-translate-add-group =
    .label = Adicionar um serviço de tradução
    .description = Em ordem alfabética, nenhum marcado; o Nulavio não tem parceria com nenhum. Ou uma instância LibreTranslate sua, ou o endereço de outro serviço.
nulavio-search-choose-group =
    .label = Escolher o provedor de pesquisa deste perfil
    .description = Um clique em "Usar" faz dele a pesquisa deste perfil: entra na lista se faltar e vira o padrão. A ordem é alfabética e nenhum vem marcado; o Nulavio não tem parceria com nenhum. Provedores com conta dizem se este perfil está conectado. Um perfil temporário esquece o login quando fecha.
nulavio-search-group =
    .label = Sugestões: quem recebe o que você digita
    .description = Com as sugestões ligadas, o que você digita na barra de endereço vai ao mecanismo antes de você pesquisar. No Nulavio, só os mecanismos ligados aqui recebem.
nulavio-search-add-group =
    .label = Mecanismos que o Nulavio sabe acrescentar
    .description = Provedores conhecidos com um clique, uma instância SearXNG sua ou a descrição OpenSearch de um site. Para montar um mecanismo à mão, use o botão de adicionar da lista acima.

## Assistente e IA

nulavio-pane-assistant =
    .heading = Assistente e IA
nulavio-pane-assistant-nav = Assistente e IA
nulavio-assistant-group =
    .label = Assistente e agentes
    .description = O assistente do Nulavio e agentes como Claude Code ou Codex usam um perfil separado (a Área de IA), só com as permissões que você define. Elas valem para todos os perfis.
nulavio-open-assistant =
    .label = Agentes, permissões e atividade
    .description = Conectar um agente como Claude Code ou Codex, dar ou tirar permissões, pausar, revogar e ver o que foi feito.

## Abas e navegação

nulavio-layout-moved-group =
    .label = Disposição das abas
nulavio-layout-moved =
    .label = Abas na lateral, no topo ou em Foco
    .description = A escolha fica em Aparência.
nulavio-shortcuts-group =
    .label = Atalhos do Nulavio
    .description = Teclas para as ações do Nulavio. Você pode trocar cada uma.
nulavio-keys-change =
    .label = Mudar os atalhos do Nulavio
    .description = Na tela do navegador, que confere cada tecla contra as do sistema e das extensões.
nulavio-keys-reset =
    .label = Restaurar os atalhos padrão

## Integrações

nulavio-pane-integrations =
    .heading = Integrações
nulavio-pane-integrations-nav = Integrações
nulavio-integrations-group =
    .label = Seu desktop
    .description = O que o seu desktop oferece ao Nulavio, verificado neste computador. A verificação não muda nada e não envia nada a lugar nenhum.
nulavio-open-integrations =
    .label = Ver as integrações

## Sobre: atualizações automáticas pelos pacotes RPM e .deb (#241)

nulavio-updates-group =
    .label = Atualizações do Nulavio
    .description = O Nulavio não se atualiza sozinho: quem atualiza é o sistema, pelo repositório assinado do Nulavio.
nulavio-updates-auto =
    .label = Atualizar o Nulavio automaticamente
    .description = Até duas vezes por dia, em segundo plano, só o Nulavio. Ligar ou desligar pede a senha de administrador.

## Sobre: novidades desta versão (#198)

nulavio-whatsnew-group =
    .label = Novidades
    .description = As notas desta versão vêm com o navegador: lê-las não envia nada a lugar nenhum.
nulavio-whatsnew-open =
    .label = Novidades desta versão
nulavio-whatsnew-notice =
    .label = Mostrar novidades após atualizar
    .description = Uma barra discreta numa janela, uma vez por versão. As notas continuam aqui e no menu Ajuda de qualquer jeito.

## Sobre: as políticas em vigor (no lugar da linha "gerenciado pela sua organização" quando são só as do Nulavio)

nulavio-policies-group =
    .label = Políticas do navegador
    .description = Regras fixadas por quem distribui ou administra o navegador. As configurações não mudam essas regras.
nulavio-policies-own =
    .label =
        { $count ->
            [one] O Nulavio aplica 1 política própria
           *[other] O Nulavio aplica { $count } políticas próprias
        }
    .description = Elas vêm com o Nulavio, e nenhuma outra está em vigor. Veja quais são.
nulavio-policies-other =
    .label =
        { $count ->
            [one] 1 política em vigor
           *[other] { $count } políticas em vigor
        }
    .description = Elas não são exatamente as que vêm com o Nulavio: um arquivo do sistema ou um administrador acrescentou, tirou ou mudou alguma. Veja quais são.

## Meeting links (#221)

nulavio-meetings-group =
    .label = Links de reunião
    .description = Para este perfil. Com “Entrar pelo navegador”, os links do Zoom e do Microsoft Teams ficam na página do serviço, que oferece entrar por ali, e nenhum app é aberto.
nulavio-meeting-links =
    .label = Quando um link de reunião abrir
nulavio-meeting-links-app =
    .label = Abrir a reunião no app (padrão)
nulavio-meeting-links-browser =
    .label = Entrar pelo navegador
