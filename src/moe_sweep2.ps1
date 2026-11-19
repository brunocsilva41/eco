$b='F:\Jarvis\bin\llama-b12531-vulkan\llama-bench.exe'; $m='F:\Jarvis\models\gptoss-20b\gpt-oss-20b-MXFP4.gguf'
foreach($n in 16,12,8){
 $o="F:\Jarvis\logs\moe-$n.txt"
 $p=Start-Process $b -ArgumentList '-m',$m,'-ngl','99','-ncmoe',$n,'-p','512','-n','128','-r','2' -PassThru -WindowStyle Hidden -RedirectStandardOutput $o -RedirectStandardError "$o.err"
 $max=0; while(-not $p.HasExited){ $v=((Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ea 0).CounterSamples|? InstanceName -match 'phys_0'|measure CookedValue -Sum).Sum/1GB; if($v -gt $max){$max=$v}; Start-Sleep 1 }
 $free=(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB
 "N=$n VRAMmax={0:N2}GB RAMlivre={1:N1}GB exit={2}" -f $max,$free,$p.ExitCode
 Get-Content $o | ? {$_ -match '^\| gpt|^\| model'} 
 if($p.ExitCode -ne 0){ Get-Content "$o.err" -Tail 3 }
}

