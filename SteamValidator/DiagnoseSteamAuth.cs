using System;
using System.Reflection;
using SteamAuth;

class DiagnoseSteamAuth
{
    static void Main()
    {
        Console.WriteLine("=== Диагностика SteamAuth ===\n");

        // 1. UserLogin
        Console.WriteLine("--- Класс UserLogin ---");
        Type userLoginType = typeof(UserLogin);
        MethodInfo[] methods = userLoginType.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
        foreach (var m in methods)
        {
            Console.WriteLine($"Метод: {m.Name}");
        }

        // 2. AuthenticatorLinker
        Console.WriteLine("\n--- Класс AuthenticatorLinker ---");
        Type linkerType = typeof(AuthenticatorLinker);
        methods = linkerType.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly);
        foreach (var m in methods)
        {
            Console.WriteLine($"Метод: {m.Name}");
        }

        // 3. Результаты
        Console.WriteLine("\n--- Enum LoginResult ---");
        foreach (var name in Enum.GetNames(typeof(LoginResult)))
        {
            Console.WriteLine(name);
        }

        Console.WriteLine("\n--- Enum LinkResult ---");
        foreach (var name in Enum.GetNames(typeof(LinkResult)))
        {
            Console.WriteLine(name);
        }

        Console.WriteLine("\n--- Enum FinalizeResult ---");
        foreach (var name in Enum.GetNames(typeof(FinalizeResult)))
        {
            Console.WriteLine(name);
        }

        // 4. SteamGuardAccount свойства
        Console.WriteLine("\n--- Свойства SteamGuardAccount ---");
        PropertyInfo[] props = typeof(SteamGuardAccount).GetProperties();
        foreach (var p in props)
        {
            Console.WriteLine($"{p.Name} : {p.PropertyType.Name}");
        }

        Console.WriteLine("\nНажмите любую клавишу...");
        Console.ReadKey();
    }
}