#include <stdio.h>
#include <stdlib.h>

int main(void) {
    FILE *pipe = popen("curl -fsS https://example.com/status", "r");
    if (pipe == NULL) {
        return 1;
    }
    pclose(pipe);
    return 0;
}
