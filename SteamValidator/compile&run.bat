cd C:\Users\vaprub\Desktop\NeuroKey\SteamValidator
dotnet add package SteamAuthStandart
dotnet clean
dotnet publish -c Release -r win-x64 --self-contained false
cd C:\Users\vaprub\Desktop\NeuroKey\SteamValidator\bin\Release\net8.0\win-x64
SteamValidator.exe warioros1 Prubnyak333999 27XZQ-VEZBR-M65I2
cmd /k