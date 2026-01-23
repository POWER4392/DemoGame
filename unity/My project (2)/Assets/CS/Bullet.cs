using UnityEngine;

public class Bullet : MonoBehaviour
{
    public float speed = 20f;
    // Start is called once before the first execution of Update after the MonoBehaviour is created
    void Start()
    {
        
    }

    // Update is called once per frame
void Update()
{
    var newPosition = transform.position;
    newPosition.y += Time.deltaTime * speed;
    transform.position = newPosition;
}
}
