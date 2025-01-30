#!/bin/bash

set -euxo pipefail

CHECK_RELEASE=${CHECK_RELEASE:-"main"}

REPO="openstack-ironic-python-agent"

line=$(grep "$REPO@" requirements.cachito)
echo $line
REPO_full=$(echo $line | cut -d "+" -f 2)
echo $REPO_full
commit_hash=$(echo $REPO_full | cut -d "@" -f 2)
echo $commit_hash
git_url=$(echo $REPO_full | cut -d "@" -f 1)
echo $git_url
git clone $git_url
pushd $REPO
git checkout $CHECK_RELEASE
if git merge-base --is-ancestor $commit_hash HEAD; then
  echo "commit $commit_hash is in $CHECK_RELEASE"
else
  echo "commit $commit_hash does not belong to $CHECK_RELEASE"
  WRONG_HASH+="$REPO "
fi
popd
rm -fr $REPO


if [ -n "${WRONG_HASH:-}" ]; then
  echo "Wrong commit hash for repo: $WRONG_HASH"
  exit 1
fi

echo "All commit hashes have been successfully verified"
