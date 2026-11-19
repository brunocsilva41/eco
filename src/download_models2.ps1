foreach($l in Get-Content F:\Jarvis\src\models2.txt){ $i=$l -split '\|'; $dir="F:\Jarvis\models\$($i[0])"; New-Item -ItemType Directory -Force $dir|Out-Null; $f="$dir\$($i[2])"
 for($t=0;$t -lt 6;$t++){ curl.exe -L -C - -s -o $f "https://huggingface.co/$($i[1])/resolve/main/$($i[2])"; $h=(Get-FileHash $f -Algorithm SHA256).Hash.ToLower(); if($h -eq $i[3]){break} }
 "$($i[0])/$($i[2]) $(if($h -eq $i[3]){'HASH_OK'}else{'HASH_FAIL'})" }
'DONE'
