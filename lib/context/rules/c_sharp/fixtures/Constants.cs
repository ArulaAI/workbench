namespace Example;

public class Constants
{
    // Should match csharp-constant
    public const int MaxRetries = 3;
    public const string ApiBaseUrl = "https://api.example.com";
    private const long DefaultTimeoutMs = 30000;

    // NOT constants — not const
    public static int MutableStatic = 0;
    private int _instanceField = 42;

    public void DoStuff()
    {
        int localVar = 99;
        Console.WriteLine(localVar);
    }

    public Constants()
    {
        _instanceField = 10;
    }
}

public struct MyStruct
{
    public int Value;
}

public interface IMyInterface
{
    void DoThing();
}

public enum Color
{
    Red,
    Green,
    Blue
}
