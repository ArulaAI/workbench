#define MAX_RETRIES 3
#define API_BASE_URL "https://api.example.com"
#define DEFAULT_TIMEOUT_MS 30000

/* NOT constants — lowercase macro */
#define helper_fn(x) ((x) + 1)

struct MyStruct {
    int value;
    char name[64];
};

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
