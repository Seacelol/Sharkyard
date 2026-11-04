@echo off
rem Sobe o tunel rapido da Cloudflare em segundo plano (sem janela) e mostra o link para os amigos.
rem Rode depois do sharkyard.bat. Para desligar o tunel: taskkill /im cloudflared.exe /f
cd /d "%~dp0"
taskkill /im cloudflared.exe /f >nul 2>&1
del cloudflared.log 2>nul
powershell -NoProfile -Command "Start-Process cloudflared -ArgumentList 'tunnel','--url','http://localhost:8080','--logfile','cloudflared.log' -WindowStyle Hidden"
echo Abrindo o tunel...
powershell -NoProfile -Command "$u=$null; for($i=0; $i -lt 40 -and -not $u; $i++){ Start-Sleep 1; if(Test-Path cloudflared.log){ $m = Select-String -Path cloudflared.log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1; if($m){ $u = $m.Matches[0].Value } } }; if($u){ Set-Clipboard $u; Write-Host ''; Write-Host ('Link para os amigos: ' + $u); Write-Host '(ja copiado, e so colar)' } else { Write-Host 'Nao achei o link em 40 segundos. Veja o arquivo cloudflared.log nesta pasta.' }"
echo.
pause
