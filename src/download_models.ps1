$ErrorActionPreference='Stop'
$items=@(
 @('qwen3vl-4b','Qwen/Qwen3-VL-4B-Instruct-GGUF','Qwen3VL-4B-Instruct-Q4_K_M.gguf','66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a'),
 @('qwen3vl-4b','Qwen/Qwen3-VL-4B-Instruct-GGUF','mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf','30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d'),
 @('gemma3-4b','ggml-org/gemma-3-4b-it-GGUF','gemma-3-4b-it-Q4_K_M.gguf','882e8d2db44dc554fb0ea5077cb7e4bc49e7342a1f0da57901c0802ea21a0863'),
 @('gemma3-4b','ggml-org/gemma-3-4b-it-GGUF','mmproj-model-f16.gguf','8c0fb064b019a6972856aaae2c7e4792858af3ca4561be2dbf649123ba6c40cb'),
 @('qwen3vl-8b','Qwen/Qwen3-VL-8B-Instruct-GGUF','Qwen3VL-8B-Instruct-Q4_K_M.gguf','67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2'),
 @('qwen3vl-8b','Qwen/Qwen3-VL-8B-Instruct-GGUF','mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf','c6ba85508d82f42590e6eb77d5340369ab6fecf107a7561d809523d8aa5f3bfd'))
foreach($i in $items){ $dir="F:\Jarvis\models\$($i[0])"; New-Item -ItemType Directory -Force $dir|Out-Null
 $f="$dir\$($i[2])"; curl.exe -L -C - -s -o $f "https://huggingface.co/$($i[1])/resolve/main/$($i[2])"
 $h=(Get-FileHash $f -Algorithm SHA256).Hash.ToLower(); "$($i[2]) $(if($h -eq $i[3]){'HASH_OK'}else{'HASH_FAIL '+$h})" }
'DONE'
