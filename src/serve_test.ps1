param($name,$model,$mmproj)
$bin='F:\Jarvis\bin\llama-b12531-vulkan\llama-server.exe'
function Vram{ ((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue).CounterSamples | ? {$_.InstanceName -match 'phys_0'} | measure CookedValue -Sum).Sum/1GB }
$base=Vram
$p=Start-Process $bin -ArgumentList '-m',$model,'--mmproj',$mmproj,'-ngl','99','-c','4096','--host','127.0.0.1','--port','8089','--jinja','--reasoning','off' -PassThru -WindowStyle Hidden -RedirectStandardError "F:\Jarvis\logs\server-$name.err"
for($i=0;$i -lt 90;$i++){ try{ if((Invoke-RestMethod http://127.0.0.1:8089/health).status -eq 'ok'){break} }catch{}; Start-Sleep 2 }
$body=@{messages=@(@{role='system';content='Você é o Jarvis, assistente em português do Brasil. Responda curto.'},@{role='user';content='Bom dia! Que horas devo sair de casa se a reunião é às 9h e levo 40 minutos no trânsito?'});max_tokens=120;temperature=0.3}|ConvertTo-Json -Depth 6
$sw=[Diagnostics.Stopwatch]::StartNew(); $r=Invoke-RestMethod http://127.0.0.1:8089/v1/chat/completions -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType 'application/json; charset=utf-8'; $sw.Stop()
$tools=@(@{type='function';function=@{name='abrir_app';description='Abre um aplicativo no Windows';parameters=@{type='object';properties=@{nome=@{type='string'}};required=@('nome')}}})
$b2=@{messages=@(@{role='user';content='Abre o bloco de notas pra mim'});tools=$tools;max_tokens=100;temperature=0}|ConvertTo-Json -Depth 8
$r2=Invoke-RestMethod http://127.0.0.1:8089/v1/chat/completions -Method Post -Body ([Text.Encoding]::UTF8.GetBytes($b2)) -ContentType 'application/json; charset=utf-8'
$v=Vram
"MODEL $name | VRAM base {0:N2} GB -> com modelo {1:N2} GB (delta {2:N2})" -f $base,$v,($v-$base)
"CHAT ($($sw.Elapsed.TotalSeconds.ToString('N1'))s, $($r.usage.completion_tokens) tok): $($r.choices[0].message.content)"
"TOOL: " + ($r2.choices[0].message | ConvertTo-Json -Depth 6 -Compress)
Stop-Process $p -Force


