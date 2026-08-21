#define MAX_RETRIES 3
#define API_BASE_URL "https://api.example.com"
#define DEFAULT_TIMEOUT_MS 30000

/* NOT constants — lowercase macro */
#define helper_fn(x) ((x) + 1)

constexpr int BATCH_SIZE = 100;
static constexpr double PI_VALUE = 3.14159;

class MyClass {
    void method() {
        int local = 42;
    }
};

struct MyStruct {
    int value;
};

namespace MyNamespace {
    void helper() {}
}

enum Color {
    RED,
    GREEN,
    BLUE
};

typedef unsigned long size_type;

void do_stuff(int n) {
    int local = n + 1;
    return;
}
