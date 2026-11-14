# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

## O seletor de perfis do engine (about:profilemanager), com perfis protegidos (#43).
## As mesmas palavras da página de desbloqueio do Shell (_locales: vault*).

nulavio-chooser-locked = Bloqueado
nulavio-chooser-headline = Este perfil está bloqueado
nulavio-chooser-explain = { $profile } mantém seus arquivos criptografados até você desbloquear.
nulavio-chooser-password = Senha do perfil
nulavio-chooser-recovery = Código de recuperação
nulavio-chooser-unlock = Desbloquear
nulavio-chooser-unlock-recovery = Desbloquear com o código
nulavio-chooser-use-keyring = Usar meu login do computador
nulavio-chooser-use-recovery = Usar o código de recuperação
nulavio-chooser-cancel = Cancelar
nulavio-chooser-back = Voltar
nulavio-chooser-open = Abrir { $profile }
nulavio-chooser-unlocking = Desbloqueando…
nulavio-chooser-no-master-key = O Nulavio não tem chave mestra: sem um dos jeitos de desbloquear deste perfil, ninguém consegue abri-lo, nem o Nulavio.
nulavio-chooser-wrong-password = Essa senha não desbloqueou o perfil.
nulavio-chooser-wrong-recovery = Esse código de recuperação não desbloqueou o perfil.
nulavio-chooser-recovery-malformed = Um código de recuperação tem 28 letras e números, em 7 grupos de 4.
nulavio-chooser-recovery-required = Este perfil não tem mais outro jeito de desbloquear. Digite o código de recuperação abaixo.
nulavio-chooser-keyring-unavailable = Seu login do computador não conseguiu desbloquear (o chaveiro do sistema não está disponível ou não tem mais a chave). Use a senha ou o código de recuperação.
nulavio-chooser-unavailable-headline = Perfis protegidos não estão disponíveis
nulavio-chooser-storage-missing = Falta neste computador o que os perfis protegidos precisam (gocryptfs e FUSE, ou libsodium). Instale e tente de novo.
nulavio-chooser-gone-headline = Este perfil não existe mais
nulavio-chooser-gone = Ele pode ter sido excluído. Nada foi alterado.
nulavio-chooser-unread-headline = Não foi possível ler este perfil
nulavio-chooser-unexpected = Algo deu errado. Nada foi alterado.
nulavio-chooser-recovery-finished = A troca do código de recuperação que tinha ficado pela metade foi concluída: o código novo abre este perfil, o anterior não abre mais.
nulavio-chooser-recovery-undone = A troca do código de recuperação que tinha ficado pela metade foi desfeita: o código anterior ainda abre este perfil, o novo não. Para ter um novo, troque de novo nos métodos de desbloqueio do perfil.
nulavio-chooser-recovery-unsettled = Não foi possível concluir agora a troca do código de recuperação que tinha ficado pela metade: os dois códigos ainda abrem este perfil. Isso é tentado de novo na próxima vez que o perfil for desbloqueado.
nulavio-chooser-recovery-unknown = Não dá para saber se a troca do código de recuperação que tinha ficado pela metade foi concluída: o arquivo de chaves não pôde ser gravado nem lido de volta. Os métodos de desbloqueio do perfil mostram qual código ele tem.
nulavio-chooser-not-recorded = A alteração foi salva, mas não pôde ser registrada dentro do perfil. Bloqueie o perfil, se estiver aberto, e desbloqueie uma vez para registrá-la.
