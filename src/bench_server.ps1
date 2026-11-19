param($name); $extra=$env:JARVIS_EXTRA
$bin='F:\Jarvis\bin\llama-b12531-vulkan\llama-server.exe'
$M='F:\Jarvis\models'
$cfg=@{ 'gemma4'=@("$M\gemma4-e4b\gemma-4-E4B-it-Q4_0.gguf","$M\gemma4-e4b\mmproj-gemma-4-E4B-it-Q8_0.gguf"); 'gptoss'=@("$M\gptoss-20b\gpt-oss-20b-MXFP4.gguf",$null) }[$name]
$a=@('-m',$cfg[0],'-ngl','99','-c','4096','--host','127.0.0.1','--port','8090','--jinja','--reasoning','off')
if($cfg[1]){$a+=@('--mmproj',$cfg[1])}
$a+= ($extra -split ' ' | ? {$_})
$p=Start-Process $bin -ArgumentList $a -PassThru -WindowStyle Hidden -RedirectStandardError "F:\Jarvis\logs\srv-$name.err"
$ok=$false; for($i=0;$i -lt 150;$i++){ if($p.HasExited){break}; try{ if((Invoke-RestMethod http://127.0.0.1:8090/health).status -eq 'ok'){$ok=$true;break} }catch{}; Start-Sleep 2 }
if(-not $ok){ "FALHOU ao subir: $extra"; Get-Content "F:\Jarvis\logs\srv-$name.err" -Tail 5; if(-not $p.HasExited){Stop-Process $p -Force}; return }
$body=@{messages=@(@{role='user';content='Explique em um parágrafo o que é um assistente de voz local e por que rodar sem nuvem é útil.'});max_tokens=200;temperature=0;seed=1}|ConvertTo-Json -Depth 5
for($k=0;$k -lt 3;$k++){ $r=Invoke-RestMethod http://127.0.0.1:8090/v1/chat/completions -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json; charset=utf-8'
 "{0} [{1}] run{2}: pp {3:N0} t/s, tg {4:N2} t/s ({5} tok){6}" -f $name,$extra,$k,$r.timings.prompt_per_second,$r.timings.predicted_per_second,$r.usage.completion_tokens,$(if($r.timings.draft_n){" draft_n=$($r.timings.draft_n) acc=$($r.timings.draft_n_accepted)"}) }
Stop-Process $p -Force

