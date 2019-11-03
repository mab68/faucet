#/bin/bash
echo 'scripts/' >> .gitignore
echo 'untrack_scripts.sh' >> .gitignore
git rm -r --cached scripts/
git add .gitignore
git commit -m "untrack"
