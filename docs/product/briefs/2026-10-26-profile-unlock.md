# Brief: profile authentication and unlock (phone, OS, password, security key)

Received from the maintainer on 2026-10-26, kept verbatim (Portuguese) as the source of requirements for roadmap phase 2c. Sequencing: [execution plan](../execution-plan.md) slices S2, S3, S5, S6, S9, S10.

---

Você é o Principal Security Architect, Cryptography Engineer, Linux/Windows Platform Engineer, Mobile Security Engineer e UX Designer do projeto NULAVIO.

## CONTEXTO

O Nulavio é um navegador Linux-first baseado inicialmente em Firefox/Gecko, com foco em privacidade, segurança por padrão, proteção contra infostealers e excelente UX/UI.

Já existem funcionalidades desenvolvidas no repositório. Preserve o trabalho atual.

Estamos desenvolvendo:
- Nulavio Guard.
- Nulavio Vault.
- Nulavio Secure Profiles.
- Nulavio Shell.
- Smart Profile Routing.

Este trabalho trata EXCLUSIVAMENTE da autenticação e do desbloqueio de perfis Nulavio.

Não desenvolver um novo gerenciador de passkeys para websites.
Não modificar o WebAuthn usado pelas páginas.
Não construir um sistema de login remoto obrigatório.
Não confundir passkeys de websites com a proteção criptográfica do perfil local.

## OBJETIVO

Permitir que o usuário desbloqueie perfis criptografados utilizando, em ordem de conveniência e compatibilidade:

1. Celular Android ou iPhone, com biometria/PIN.
2. Autenticação local disponível no sistema operacional.
3. Senha própria do perfil.
4. YubiKey ou autenticador FIDO2 compatível, opcional.

O celular deve ser uma opção principal e acessível, não uma funcionalidade exclusiva para usuários avançados.

Quero que o Nulavio ofereça segurança forte por padrão com mínimo atrito de configuração.

## PRINCÍPIO CENTRAL

Uma autenticação bem-sucedida só deve liberar dados criptografados se participar efetivamente da autorização e/ou liberação da chave necessária para descriptografá-los.

NÃO implementar um botão de aprovação de celular que simplesmente esconda uma tela de bloqueio enquanto os dados continuam acessíveis.

NÃO manter uma chave automaticamente acessível no desktop e afirmar que ela está protegida pela passkey do celular.

NÃO confundir verificação biométrica com proteção criptográfica.

NÃO assumir que uma assinatura FIDO2 comum pode ser utilizada diretamente como chave simétrica.

## SEPARAÇÃO DE COMPONENTES

1. Nulavio Vault
   - Criptografia em repouso.
   - Data Encryption Keys por perfil.
   - Envelope encryption.
   - Ciclo de vida das chaves.
   - Lock/unlock criptográfico.
   - Recovery e migração.

2. Nulavio Unlock Coordinator
   - Gerenciamento das políticas de desbloqueio.
   - Escolha de autenticação.
   - Verificação de capacidades.
   - Estado de bloqueio.
   - Comunicação com métodos autorizados.
   - Proteção contra downgrade.
   - Cancelamento e timeout.

3. Nulavio Platform Key Provider
   - Windows DPAPI/CNG/Windows Hello.
   - Linux Secret Service/KWallet quando aplicável.
   - Password-derived key.
   - TPM e hardware-backed providers quando disponíveis.

4. Nulavio Phone Unlock
   - Autenticação com telefone.
   - Pareamento.
   - Comunicação segura.
   - Liberação de material criptográfico.
   - Gerenciamento de aparelhos.
   - Recuperação.

5. Nulavio Hardware Key Provider
   - YubiKey e outros autenticadores FIDO2.
   - PRF/hmac-secret quando disponível.
   - PIN/User Verification.
   - Capability detection.
   - Integração com Vault.

## FASE 0 — PESQUISA OBRIGATÓRIA

Compare tecnicamente três alternativas.

### A. WEB AUTHN HYBRID + PRF

Investigue:
- Passkeys armazenadas em Android e iPhone.
- Cross-Device Authentication.
- Transporte hybrid/caBLE.
- QR Code.
- Bluetooth/proximity requirements.
- WebAuthn PRF extension.
- Capacidade de obter PRF durante fluxo híbrido.
- Consistência de PRF após sincronização de passkeys.
- Windows WebAuthn API.
- Limitações atuais de Firefox/Gecko no Linux.
- Possibilidade de uso em aplicativos nativos locais.
- Dependências de serviços de terceiros.
- Necessidade de RP ID/origin válidos.
- Comportamento offline.
- Requisitos de interação do usuário.

Não assumir que autenticação WebAuthn híbrida fornece PRF.

Não usar uma assinatura válida como substituto do segredo criptográfico necessário para recuperar a DEK.

Avaliar suporte real por combinação:
Windows + Android
Windows + iPhone
Linux + Android
Linux + iPhone

Cada combinação deve receber um estado:
SUPPORTED_AND_TESTED
DOCUMENTED_NOT_TESTED
EXPERIMENTAL
UNSUPPORTED
UNKNOWN

### B. NULAVIO COMPANION

Investigue um aplicativo Android/iOS pequeno, dedicado somente ao desbloqueio de perfis.

Não será um navegador nem gerenciador de senhas.

O aplicativo deverá:
- Registrar um desktop confiável.
- Proteger material criptográfico no celular.
- Exigir biometria forte ou credencial local apropriada.
- Autorizar uma operação específica de desbloqueio.
- Comunicar-se por canal autenticado e criptografado.
- Permitir remover pareamentos.
- Não exigir conta Nulavio.
- Não exigir serviço de nuvem.
- Funcionar na rede local quando tecnicamente possível.
- Ter recuperação segura para troca/perda do telefone.
- Evitar permissões invasivas.

Android:
- Android Keystore.
- StrongBox quando disponível e aplicável.
- BiometricPrompt.
- Chaves não exportáveis quando suportadas.
- Autorização criptográfica vinculada à autenticação.
- Verificação da capacidade de proteção por hardware.

iOS:
- Keychain.
- Secure Enclave.
- LocalAuthentication.
- Face ID/Touch ID.
- SecAccessControl.
- CryptoKit.
- Chaves protegidas com política de uso adequada.

Avaliar limitações de background execution, Bluetooth, Wi-Fi, descoberta de dispositivos e notificações.

### C. APPROVAL-ONLY

Avaliar aprovação remota simples como alternativa de UX.

Se a chave de descriptografia permanecer automaticamente acessível a qualquer processo com privilégios equivalentes no desktop, NÃO classificar como desbloqueio criptográfico forte.

Registrar as limitações e rejeitar o uso desse método como principal controle anti-infostealer.

Criar docs/adr/phone-profile-unlock.md contendo:
- Comparação.
- Evidências.
- Modelo de ameaça.
- Compatibilidade.
- Custos de manutenção.
- Recomendação.
- Critérios para implementação.
- Critérios de cancelamento.

## DECISÃO ARQUITETURAL PREFERIDA

Preferir WebAuthn híbrido com PRF SOMENTE quando o fluxo de liberação de chave for demonstradamente seguro, estável e compatível.

Na ausência dessa garantia, recomendar Nulavio Companion como arquitetura multiplataforma.

Não afirmar que Nulavio Companion utiliza WebAuthn/passkeys se ele estiver utilizando outro protocolo de autenticação e liberação criptográfica.

A interface pode chamar o recurso de "Desbloquear com celular", sem confundir o usuário com detalhes de protocolo.

## NULAVIO VAULT

Projetar:

- Profile DEK aleatória por perfil.
- Envelope encryption.
- Métodos de desbloqueio independentes.
- AEAD para proteção de material de chave.
- Metadata versionada.
- Domain separation.
- Gestão de ciclos de vida.
- Rotação de key wrapping.
- Crash consistency.
- Backup/recovery.

As cópias protegidas da DEK devem existir apenas onde necessário.

Ao cadastrar novo telefone, nova chave ou método de recuperação, criar novo envelope autorizado, sem exigir criptografar todos os dados novamente quando isso não for necessário.

Não armazenar a DEK em texto claro no perfil.

Não implementar criptografia própria.

Não fazer integração direta em cookies.sqlite, IndexedDB ou outros armazenamentos Gecko antes de validar a POC independente e definir uma arquitetura segura de persistência.

## NULAVIO PHONE UNLOCK — MODELO PREFERIDO

1. Pareamento inicial:
   - Desktop gera desafio e identidade criptográfica para pareamento.
   - Exibe QR Code de uso único.
   - Celular verifica o convite e inicia pareamento autenticado.
   - Usuário confirma a identidade do dispositivo.
   - Estabelecer chaves/identidades duradouras para pareamento.
   - Evitar ataques man-in-the-middle e substitution.
   - Não confiar no QR Code como autenticação suficiente por si só.
   - Vincular pareamento a instalação/dispositivo e perfil autorizado.

2. Proteção da chave:
   - A credencial ou envelope móvel deve ser protegido por mecanismos do SO do telefone.
   - Uso deve exigir autenticação local adequada.
   - Não enviar chave em texto claro por rede.
   - Não armazenar segredo reutilizável em logs ou clipboard.
   - Material sensível não deve ser disponibilizado a componentes não autorizados.

3. Desbloqueio:
   - Desktop gera desafio novo e não reutilizável.
   - Vincular desafio a perfil, dispositivo, operação e expiração.
   - Celular exibe solicitação com contexto suficiente.
   - Usuário autentica localmente.
   - Operação criptográfica autorizada libera o material necessário ao desktop por canal E2E autenticado.
   - Desktop valida o resultado e recupera a Profile DEK.
   - Descartar material intermediário quando possível.
   - Impedir replay e substituição de respostas.

4. Transporte:
   - Priorizar comunicação local segura quando viável.
   - Investigar QR Code como fallback previsível.
   - Avaliar Bluetooth e rede local sem permissões desnecessárias.
   - Relay pela internet somente se futuro requisito justificar.
   - Relay nunca pode descriptografar material de desbloqueio.
   - Não depender de disponibilidade de servidor Nulavio para desbloqueio normal.

5. Recuperação:
   - Telefone perdido.
   - Telefone trocado.
   - App desinstalado.
   - Biometria indisponível.
   - Keystore invalidado.
   - Sem rede local.
   - Bluetooth indisponível.
   - Dispositivo não reconhecido.
   - Migração Linux -> Windows.
   - Restauração de backup criptografado.

Projetar suporte a pelo menos dois métodos de recuperação antes de classificar Phone Unlock como pronto para distribuição.

A recuperação pode envolver segundo dispositivo ou recovery code de alta entropia.

Nunca criar recuperação por PIN curto sem mecanismos criptográficos e políticas apropriadas.

## POLÍTICAS DE SEGURANÇA — DEFAULTS

Quero a experiência mais segura possível sem comprometer excessivamente a usabilidade.

DEVE SER PADRÃO:
- Isolamento de perfis.
- Criptografia em repouso dos dados sensíveis que a arquitetura conseguir proteger corretamente.
- Nenhum armazenamento de DEK em texto claro.
- Uso dos mecanismos de segurança do sistema operacional.
- Proteções Gecko preservadas.
- Ausência de telemetry Nulavio por padrão.
- Nenhuma integração remota obrigatória.
- Nenhum unlock silencioso por método que o usuário configurou como obrigatório.
- Bloqueio real quando solicitado.
- Métodos de recuperação claramente apresentados.
- Configuração de segurança compreensível.
- Nenhum downgrade silencioso quando o dispositivo não estiver disponível.

DEVE SER RECOMENDADO:
- Desbloqueio com celular, depois que houver implementação criptograficamente válida e suporte testado.
- Autenticação com biometria/PIN do celular.
- Recovery code.
- Segundo método de recuperação.
- Bloqueio automático de perfis sensíveis.
- Reautenticação para exportações e mudanças de proteção.

DEVE SER OPCIONAL:
- YubiKey/FIDO2.
- Exigir senha + celular.
- Exigir senha + YubiKey.
- Perfil bancário com política mais restrita.
- Perfil efêmero.
- Bloqueio automático quando telefone/chave desconectar.
- Exigência de confirmação por operação.
- Uso de serviços remotos de retransmissão.
- Configurações avançadas de hardware.

Na ausência de Phone Unlock funcional:
- Usar autenticação local confiável e/ou senha criptográfica.
- Não impedir o uso do navegador por falta de telefone.
- Não oferecer proteção aparente que não corresponda ao mecanismo implementado.
- Não salvar dados sem proteção silenciosamente.

Criar matriz separada de disponibilidade e proteção efetiva.
Diferenciar:
encrypted_at_rest
os_user_protected
password_protected
hardware_bound
phone_approved
phone_key_release_verified

Não tratar esses estados como equivalentes.

## UX/UI — OBJETIVO PRINCIPAL

Nulavio deve ser extremamente seguro e muito simples de configurar.

Projetar um onboarding com no máximo três decisões principais:
1. Criar ou escolher perfil.
2. Selecionar método de proteção.
3. Configurar recuperação e concluir.

Evitar termos como CTAP2, PRF, HKDF, AEAD ou RP ID na interface comum.

Usar linguagem clara:
- Desbloquear com celular.
- Usar uma senha.
- Usar chave de segurança.
- Adicionar outro dispositivo.
- Recuperar acesso.
- Bloquear perfil.

Criar telas:
1. Escolha de método de desbloqueio.
2. Conectar celular.
3. QR Code.
4. Confirmar pareamento.
5. Celular conectado.
6. Testar desbloqueio.
7. Configurar recuperação.
8. Perfil bloqueado.
9. Solicitação enviada ao celular.
10. Aprovar com biometria/PIN.
11. Celular indisponível.
12. Usar outro método.
13. Gerenciar dispositivos autorizados.
14. Remover celular perdido.
15. Alterar política do perfil.

Interface deve:
- Respeitar o design system Nulavio Horizon.
- Usar componentes e tokens existentes.
- Ter dark/light mode.
- Ser acessível.
- Ter feedback claro e discreto.
- Exibir erros acionáveis.
- Permitir cancelamento.
- Não mostrar identificadores sensíveis.
- Não exibir detalhes de segurança desnecessários.
- Ser consistente entre Linux e Windows.

Projetar estados:
idle
pairing
waiting_for_phone
waiting_for_biometric
authorized
unlocking
unlocked
timeout
cancelled
device_unavailable
recovery_required
error

Todas as telas devem representar operações reais.
Não criar controles decorativos ou funcionais falsos.

## ANTI-INFOSTEALER THREAT MODEL

Modelar:
- Roubo offline do perfil.
- Malware executando como mesmo usuário.
- Malware com root/administrator.
- IPC comprometido.
- Pareamento fraudulento.
- QR Code substituído.
- Replay.
- Desktop falso pedindo aprovação.
- Usuário enganado para aprovar solicitação.
- Celular comprometido.
- Comprometimento do Companion.
- Sessão ativa e material de chave em memória.
- Dados expostos por extensões.
- Logs contendo segredos.
- Recovery code roubado.
- Perda de dispositivo.
- Downgrade para desbloqueio fraco.
- Troca de usuário/perfil durante operação.
- Operação de desbloqueio após expiração.

Definir trust boundaries e controles para cada cenário.

Não prometer proteção contra malware que já possui controle irrestrito do processo e de sua memória.

## RECUPERAÇÃO E RESILIÊNCIA

Os dados não podem ficar inacessíveis por um erro transitório de rede ou ausência temporária do telefone.

Implementar:
- Método alternativo de desbloqueio.
- Recovery code de alta entropia.
- Múltiplos dispositivos.
- Remoção/revogação.
- Repareamento.
- Teste de recuperação durante onboarding.
- Migração entre sistemas.
- Backup criptografado.
- Atomicidade.
- Tratamento de corrupção.

Se o usuário perder todos os fatores e métodos de recuperação, explicar a impossibilidade criptográfica de recuperação.

Não implementar backdoor ou chave mestra Nulavio.

## TESTES

Testes obrigatórios:
- Perfil não desbloqueia sem método válido.
- O celular aprovado consegue liberar o material necessário.
- A simples ausência de erro de autenticação não equivale a sucesso criptográfico.
- Não é possível recuperar a DEK copiando apenas os arquivos protegidos.
- Desafio expirado falha.
- Resposta repetida falha.
- Aparelho não pareado falha.
- Pareamento substituído falha.
- Cancelamento falha de modo seguro.
- Rede indisponível oferece método alternativo.
- Segundo aparelho recupera perfil.
- Recovery code funciona.
- PIN/biometria indisponíveis têm tratamento claro.
- Dados permanecem recuperáveis após atualização.
- Bloqueio encerra corretamente acesso sensível.
- Falha de processo não grava segredos em texto claro.

Executar testes no Fedora KDE.
Preparar matriz Windows.
Planejar Android primeiro como POC móvel, sem excluir iOS da arquitetura.
Não declarar compatibilidade iOS sem testes reais.

## MILESTONES

M0: Auditoria do repositório.
M1: Estudo formal WebAuthn híbrido + PRF versus Companion.
M2: ADR de escolha do protocolo.
M3: Threat model e key management.
M4: Protótipo de desbloqueio criptográfico com dados artificiais.
M5: Prova de pareamento desktop/celular.
M6: Implementação Android POC com Android Keystore.
M7: Testes de recovery, replay e dispositivos perdidos.
M8: Integração ao Nulavio Vault.
M9: UX/UI e onboarding completo.
M10: Avaliação de port para iOS e Windows.
M11: Hardening e auditoria independente.

(Roadmap names these U0–U11 to avoid clashing with other milestone series.)

## EXECUÇÃO DESTA SESSÃO

1. Inspecionar o código atual.
2. Confirmar arquitetura e versão do Gecko.
3. Criar relatório de compatibilidade com fontes oficiais.
4. Identificar o que é possível implementar sem um Companion e o que exige aplicativo móvel.
5. Criar ADR de autenticação e desbloqueio com celular.
6. Criar diagrama de trust boundaries e fluxo de chaves.
7. Definir os padrões seguros e a UX de onboarding.
8. Criar mockups e componentes iniciais reutilizando o design system.
9. Implementar uma POC de desbloqueio criptográfico isolada, sem dados reais.
10. Executar testes e documentar resultados.
11. Apresentar plano de evolução Android/iOS e Windows.

Não iniciar construção indiscriminada de um aplicativo móvel completo antes de aprovar a arquitetura criptográfica e o protocolo de pareamento.

Não assumir que WebAuthn PRF funciona em transporte híbrido sem testes.

Não exigir dispositivos que o usuário não possui para continuar a implementação inicial.

## REFERÊNCIAS

- https://www.w3.org/TR/webauthn-3/
- https://developers.yubico.com/WebAuthn/Concepts/PRF_Extension/
- https://learn.microsoft.com/en-us/windows/security/identity-protection/passkeys/
- https://developer.android.com/privacy-and-security/keystore
- https://developer.android.com/identity/sign-in/biometric-auth
- https://developer.apple.com/documentation/cryptokit/secureenclave
- https://developer.apple.com/documentation/localauthentication
- https://www.rfc-editor.org/rfc/rfc9180
- https://bugzilla.mozilla.org/show_bug.cgi?id=1543674

COMECE COM UMA RECOMENDAÇÃO FUNDAMENTADA E UMA POC SEGURA. NÃO PARE APENAS EM DOCUMENTAÇÃO QUANDO FOR POSSÍVEL IMPLEMENTAR.
