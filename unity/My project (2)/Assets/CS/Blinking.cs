using UnityEngine;

public class Blinking : MonoBehaviour

{
private SpriteRenderer spriteRenderer;

// Start is called before the first frame update
void Start()
{
spriteRenderer = GetComponent<SpriteRenderer>();
}

// Update is called once per frame
void Update()
{
spriteRenderer.enabled = !spriteRenderer.enabled;
}
}