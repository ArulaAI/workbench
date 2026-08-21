package com.example;

public class Constants {
    // Should match java-constant
    public static final int MAX_RETRIES = 3;
    public static final String API_BASE_URL = "https://api.example.com";
    private static final long DEFAULT_TIMEOUT_MS = 30000;

    // NOT constants — not static final
    private int instanceField = 42;
    public static int mutableStatic = 0;

    public void doStuff() {
        int localVar = 99;
        System.out.println(localVar);
    }

    public Constants() {
        this.instanceField = 10;
    }
}

interface MyInterface {
    void doThing();
}
