var s = Logica.Saude();
var ok = s["status"] == "ok" && s["servico"] == Logica.Nome;
Console.WriteLine(ok ? "ok  Logica.Saude" : "FALHOU  Logica.Saude");
return ok ? 0 : 1;
