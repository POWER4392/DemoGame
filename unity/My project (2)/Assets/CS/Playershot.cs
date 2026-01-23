using UnityEngine;

public class Playershot : MonoBehaviour
{
    public GameObject bulletPrefab; 
    public float shootingInterval = 100f; // Thời gian giãn cách giữa 2 lần bắn
    public float bulletSpeed = 0.3f;       // Tốc độ bay của đạn
    public float bulletLifeTime = 2f;     // Đạn sẽ tự hủy sau bao nhiêu giây?

    private float lastBulletTime;

    void Update()
    {
        if (Input.GetMouseButton(0))
        {
           if (Time.time - lastBulletTime > shootingInterval)
           {
               ShootBullet();
               lastBulletTime = Time.time;
           }
        }
    }

    void ShootBullet()
    {
        GameObject bullet = Instantiate(bulletPrefab, transform.position, transform.rotation);

        Rigidbody2D rb = bullet.GetComponent<Rigidbody2D>();
        
        if (rb != null)
        {
            
            rb.linearVelocity = bullet.transform.up * bulletSpeed;
        }

        Destroy(bullet, bulletLifeTime);
    }
}