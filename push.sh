
#!/data/data/com.termux/files/usr/bin/bash

echo "Enter commit message:"
read msg

git add .
git commit -m "$msg"
git push

