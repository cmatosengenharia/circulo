var app = WebApplication.CreateBuilder(args).Build();
app.MapGet("/saude", Logica.Saude);
app.Run();
