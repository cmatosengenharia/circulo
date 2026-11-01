public static class Logica
{
    public const string Nome = "{{nome}}";
    public static Dictionary<string, string> Saude() => new() { ["status"] = "ok", ["servico"] = Nome };
}
