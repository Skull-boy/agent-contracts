import java.net.http.HttpClient;

public class Client {
    public static void main(String[] args) {
        HttpClient client = HttpClient.newHttpClient();
        System.out.println(client);
    }
}
