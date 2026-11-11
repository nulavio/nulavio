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
# profile of this window.
nulavio-profile-plain =
    .label = { $name }
    .description =
        { $here ->
            [yes] Este perfil. Sem senha.
           *[no] Sem senha.
        }
nulavio-profile-unlocked =
    .label = { $name }
    .description =
        { $here ->
            [yes] Este perfil. Protegido e desbloqueado.
           *[no] Protegido. Desbloqueado agora.
        }
nulavio-profile-locked =
    .label = { $name }
    .description = Protegido e bloqueado: criptografado no disco.
nulavio-profile-temporary =
    .label = Perfil temporário
    .description = Temporário. Apagado ao fechar.
nulavio-profiles-group =
    .label = Seus perfis
    .description = Cada perfil guarda seus próprios logins, histórico e extensões. Um perfil protegido fica criptografado no disco enquanto está bloqueado.
nulavio-open-routing =
    .label = Qual site abre em qual perfil
    .description = Regras para links vindos de outros aplicativos e endereços digitados.

## Privacidade e segurança

nulavio-protections-group =
    .label = Proteções do Nulavio
    .description = O que o Nulavio acrescenta às proteções do navegador.
nulavio-open-exceptions =
    .label = Exceções de sites
    .description = Sites em que uma proteção está desligada ou relaxada, por você ou pelo próprio navegador.
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

## Senhas

nulavio-passwords-group =
    .label = Quem guarda suas senhas
    .description = Um gerenciador por perfil. O Nulavio nunca lê o seu cofre.
nulavio-passwords-now-builtin =
    .label = Em uso: o gerenciador do próprio navegador
    .description = As opções dele ficam logo abaixo.
nulavio-passwords-now-none =
    .label = O gerenciador do navegador está desligado
    .description = Nenhum dos gerenciadores que o Nulavio conhece está ligado. Outra extensão pode estar cuidando das senhas.
# $name is the name of a password manager extension.
nulavio-passwords-now-extension =
    .label = Em uso: { $name }
    .description = Uma extensão. O gerenciador do próprio navegador fica desligado.
nulavio-open-passwords =
    .label = Trocar de gerenciador
    .description = O do navegador ou um dos que o Nulavio sabe instalar pela extensão oficial.

## Pesquisa

nulavio-search-group =
    .label = Mecanismos do Nulavio
    .description = Sugestões de busca ligadas por mecanismo, e mecanismos que o navegador não traz.
nulavio-open-search =
    .label = Mecanismos e sugestões por mecanismo

## Assistente e IA

nulavio-pane-assistant =
    .heading = Assistente e IA
nulavio-pane-assistant-nav = Assistente e IA
nulavio-assistant-group =
    .label = Assistente e agentes
    .description = O assistente do Nulavio e agentes como Claude Code ou Codex usam um perfil separado (a Área de IA), só com as permissões que você define.
nulavio-open-assistant =
    .label = Assistente, agentes e atividade
    .description = Ligar o assistente, conectar um agente, pausar, revogar e ver o que foi feito.

## Abas e navegação

nulavio-layout-moved-group =
    .label = Disposição das abas
nulavio-layout-moved =
    .label = Abas na lateral, no topo ou em Foco
    .description = A escolha fica em Aparência.
nulavio-shortcuts-group =
    .label = Atalhos do Nulavio
    .description = Teclas para as ações do Nulavio. Você pode trocar cada uma.
nulavio-key-none =
    .description = Sem tecla
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
