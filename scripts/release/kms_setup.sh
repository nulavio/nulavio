#!/usr/bin/env bash
# Create, once, what CI needs to sign releases with the key held in AWS KMS:
#
# - the IAM role nulavio-release-signing, which only a GitHub Actions job of
#   nulavio/nulavio running in the `release` environment can assume (OIDC);
# - the KMS key alias/nulavio-release: RSA_4096, SIGN_VERIFY, origin EXTERNAL
#   (empty until scripts/release/kms_import_key.py imports the release key);
# - the role's only permission: Sign, GetPublicKey and DescribeKey on that key.
#
#   AWS_PROFILE=lombello-dev AWS_REGION=us-east-1 scripts/release/kms_setup.sh
#
# Reads before it writes: what exists is kept and checked, not replaced. The
# policies are in ci/aws/ (reviewed in git); the key policy lets only that role
# and the account's administrator SSO roles sign, and only with
# RSASSA_PKCS1_V1_5_SHA_256. GitHub's OIDC provider must already exist in the
# account. Prints the ARNs for the `release` environment's variables.
set -euo pipefail

: "${AWS_PROFILE:?set AWS_PROFILE explicitly}" "${AWS_REGION:?set AWS_REGION explicitly}"
export AWS_PROFILE AWS_REGION
repo_root=$(cd "$(dirname "$0")/../.." && pwd)
policies=$repo_root/ci/aws
role=nulavio-release-signing
alias=alias/nulavio-release
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

account=$(aws sts get-caller-identity --query Account --output text)
render() { sed -e "s|__ACCOUNT__|$account|g" -e "s|__ROLE__|$role|g" -e "s|__KEY_ARN__|${key_arn:-}|g" "$policies/$1" >"$work/$1"; }

aws iam get-open-id-connect-provider \
    --open-id-connect-provider-arn "arn:aws:iam::$account:oidc-provider/token.actions.githubusercontent.com" >/dev/null ||
    { echo "kms_setup: GitHub's OIDC provider is missing in account $account" >&2; exit 1; }

render release-signing-trust.json
if aws iam get-role --role-name "$role" >/dev/null 2>&1; then
    echo "role $role exists: trust policy left as it is"
else
    aws iam create-role --role-name "$role" --max-session-duration 3600 \
        --description "Nulavio: GitHub Actions release environment signs with the release key in KMS" \
        --assume-role-policy-document "file://$work/release-signing-trust.json" \
        --tags Key=project,Value=nulavio >/dev/null
    echo "role $role created"
fi

key_arn=$(aws kms describe-key --key-id "$alias" --query KeyMetadata.Arn --output text 2>/dev/null || true)
if [[ -n $key_arn && $key_arn != None ]]; then
    echo "key $alias exists: $key_arn"
else
    render release-key-policy.json
    # The role was just created: IAM can take a few seconds before KMS accepts it in a policy.
    for attempt in 1 2 3 4 5 6; do
        key_arn=$(aws kms create-key --key-spec RSA_4096 --key-usage SIGN_VERIFY --origin EXTERNAL \
            --description "Nulavio release signing key 298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1 (imported)" \
            --policy "file://$work/release-key-policy.json" --tags TagKey=project,TagValue=nulavio \
            --query KeyMetadata.Arn --output text 2>"$work/err") && break
        grep -q MalformedPolicyDocument "$work/err" && [[ $attempt -lt 6 ]] || { cat "$work/err" >&2; exit 1; }
        sleep 10
    done
    aws kms create-alias --alias-name "$alias" --target-key-id "$key_arn"
    echo "key $alias created: $key_arn"
fi

read -r spec usage origin state < <(aws kms describe-key --key-id "$key_arn" \
    --query '[KeyMetadata.KeySpec, KeyMetadata.KeyUsage, KeyMetadata.Origin, KeyMetadata.KeyState]' --output text)
echo "key: $spec $usage $origin $state"
[[ $spec == RSA_4096 && $usage == SIGN_VERIFY && $origin == EXTERNAL ]] ||
    { echo "kms_setup: $alias is not an RSA_4096 SIGN_VERIFY key with imported material" >&2; exit 1; }

render release-signing-role-policy.json
aws iam put-role-policy --role-name "$role" --policy-name sign-with-release-key \
    --policy-document "file://$work/release-signing-role-policy.json"

cat <<EOF

GitHub environment "release" variables:
  NULAVIO_KMS_KEY_ARN=$key_arn
  NULAVIO_SIGNING_ROLE_ARN=arn:aws:iam::$account:role/$role
  NULAVIO_AWS_REGION=$AWS_REGION
EOF
