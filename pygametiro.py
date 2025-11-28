import os
import random
import sys
from dataclasses import dataclass

import pygame
import serial
import serial.tools.list_ports
from serial import SerialException


WIDTH, HEIGHT = 900, 600
PLAYER_SIZE = 50
OBSTACLE_SIZE = 60
PLAYER_SPEED = 7
OBSTACLE_SPEED = 5
SPAWN_RATE_MS = 350
BULLET_WIDTH, BULLET_HEIGHT = 10, 22
BULLET_SPEED = 14
SHOT_COOLDOWN = 0.5
RED_IMMUNE = (231, 76, 60)
SERIAL_BAUD = 115200
DEFAULT_SERIAL_PORT = os.environ.get("PICO_PORT", "COM3")


@dataclass
class Entity:
    rect: pygame.Rect
    color: tuple[int, int, int]


def create_obstacle() -> Entity:
    x_pos = random.randint(0, WIDTH - OBSTACLE_SIZE)
    rect = pygame.Rect(x_pos, -OBSTACLE_SIZE, OBSTACLE_SIZE, OBSTACLE_SIZE)
    color = random.choice([RED_IMMUNE, (255, 255, 255), (255, 255, 255)])
    return Entity(rect=rect, color=color)


def create_bullet(player_rect: pygame.Rect) -> Entity:
    rect = pygame.Rect(
        player_rect.centerx - BULLET_WIDTH // 2,
        player_rect.top - BULLET_HEIGHT,
        BULLET_WIDTH,
        BULLET_HEIGHT,
    )
    return Entity(rect=rect, color=(46, 204, 113))


def clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, value))


def find_serial_port() -> str:
    try:
        ports = serial.tools.list_ports.comports()
    except Exception:
        return DEFAULT_SERIAL_PORT
    for port in ports:
        if "pico" in port.description.lower():
            return port.device
    return ports[0].device if ports else DEFAULT_SERIAL_PORT


class SerialController:
    def __init__(self, port: str, baud: int):
        self.port = port
        self.baud = baud
        self.conn = self._open()
        self.buffer = b""
        self.left = False
        self.right = False
        self.shoot = False
        self.reported_error = False

    def _open(self):
        try:
            conn = serial.Serial(self.port, self.baud, timeout=0.0)
            print(f"[Serial] Listening on {self.port} @ {self.baud}")
            return conn
        except Exception as exc:
            print(f"[Serial] Unable to open {self.port}: {exc}")
            return None

    def update(self):
        if not self.conn:
            return
        try:
            data = self.conn.read_all()
        except SerialException as exc:
            if not self.reported_error:
                print(f"[Serial] Disconnected: {exc}")
                self.reported_error = True
            return
        if not data:
            return
        self.buffer += data
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            self._handle_line(line.decode("utf-8", errors="ignore").strip())

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        parts = line.upper().split()
        name = parts[0]
        state = parts[1] if len(parts) > 1 else ""

        if name == "A":
            if state in ("DOWN", "HELD"):
                self.left = True
            elif state == "UP":
                self.left = False
        elif name == "B":
            if state in ("DOWN", "HELD"):
                self.right = True
            elif state == "UP":
                self.right = False
        elif name == "C":
            if state in ("DOWN", "HELD"):
                self.shoot = True

    def consume_shot(self) -> bool:
        if self.shoot:
            self.shoot = False
            return True
        return False


def draw_background(screen: pygame.Surface) -> None:
    top = pygame.Color(30, 39, 46)
    bottom = pygame.Color(83, 92, 104)
    for y in range(HEIGHT):
        blend = y / HEIGHT
        color = pygame.Color(
            int(top.r + (bottom.r - top.r) * blend),
            int(top.g + (bottom.g - top.g) * blend),
            int(top.b + (bottom.b - top.b) * blend),
        )
        pygame.draw.line(screen, color, (0, y), (WIDTH, y))


def render_text(screen: pygame.Surface, font: pygame.font.Font, text: str, center: tuple[int, int]) -> None:
    surface = font.render(text, True, (236, 240, 241))
    rect = surface.get_rect(center=center)
    screen.blit(surface, rect)


def reset_game():
    player_rect = pygame.Rect(WIDTH // 2 - PLAYER_SIZE // 2, HEIGHT - PLAYER_SIZE - 20, PLAYER_SIZE, PLAYER_SIZE)
    obstacles: list[Entity] = []
    bullets: list[Entity] = []
    score = 0.0
    elapsed = 0.0
    spawn_interval = SPAWN_RATE_MS
    last_shot_time = -SHOT_COOLDOWN
    return player_rect, obstacles, bullets, score, False, elapsed, spawn_interval, last_shot_time


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Skyfall Escape - Pygame")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 24)
    big_font = pygame.font.SysFont("consolas", 38, bold=True)

    spawn_event = pygame.USEREVENT + 1
    pygame.time.set_timer(spawn_event, SPAWN_RATE_MS)

    serial_controller = SerialController(find_serial_port(), SERIAL_BAUD)

    player_rect, obstacles, bullets, score, game_over, elapsed, spawn_interval, last_shot_time = reset_game()

    while True:
        dt = clock.tick(60) / 1000
        serial_controller.update()
        shoot_requested = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == spawn_event and not game_over:
                obstacles.append(create_obstacle())
            if event.type == pygame.KEYDOWN and game_over and event.key == pygame.K_r:
                player_rect, obstacles, bullets, score, game_over, elapsed, spawn_interval, last_shot_time = reset_game()

        keys = pygame.key.get_pressed()
        if not game_over:
            elapsed += dt
            if keys[pygame.K_LEFT] or keys[pygame.K_a] or serial_controller.left:
                player_rect.x -= PLAYER_SPEED
            if keys[pygame.K_RIGHT] or keys[pygame.K_d] or serial_controller.right:
                player_rect.x += PLAYER_SPEED

            shoot_requested = keys[pygame.K_SPACE] or serial_controller.consume_shot()

            player_rect.x = clamp(player_rect.x, 0, WIDTH - PLAYER_SIZE)
            player_rect.y = clamp(player_rect.y, 0, HEIGHT - PLAYER_SIZE)

            if shoot_requested and elapsed - last_shot_time >= SHOT_COOLDOWN:
                bullets.append(create_bullet(player_rect))
                last_shot_time = elapsed

            current_spawn = max(250, int(SPAWN_RATE_MS - elapsed * 35))
            if current_spawn != spawn_interval:
                spawn_interval = current_spawn
                pygame.time.set_timer(spawn_event, spawn_interval)

            obstacle_speed = min(14, OBSTACLE_SPEED + elapsed * 0.45)
            for obstacle in obstacles:
                obstacle.rect.y += obstacle_speed

            for bullet in bullets:
                bullet.rect.y -= BULLET_SPEED

            survived = []
            bullets_to_remove: set[int] = set()
            for obstacle in obstacles:
                destroyed = False
                for i, bullet in enumerate(bullets):
                    if obstacle.color == RED_IMMUNE:
                        continue
                    if obstacle.rect.colliderect(bullet.rect):
                        bullets_to_remove.add(i)
                        destroyed = True
                        score += 1
                        break
                if destroyed:
                    continue
                if obstacle.rect.colliderect(player_rect):
                    game_over = True
                    break
                if obstacle.rect.y > HEIGHT:
                    score += 1
                else:
                    survived.append(obstacle)
            obstacles = survived
            bullets = [b for idx, b in enumerate(bullets) if idx not in bullets_to_remove and b.rect.bottom > 0]

            score += dt * 2

        draw_background(screen)
        pygame.draw.rect(screen, (52, 152, 219), player_rect, border_radius=6)
        for obstacle in obstacles:
            pygame.draw.rect(screen, obstacle.color, obstacle.rect, border_radius=8)
        for bullet in bullets:
            pygame.draw.rect(screen, bullet.color, bullet.rect, border_radius=4)

        render_text(screen, font, f"Score: {int(score)}", (90, 26))
        render_text(screen, font, "Serial: A/B move, C shoot", (WIDTH - 190, 26))
        render_text(screen, font, "Keyboard: A/D + SPACE", (WIDTH - 150, 54))
        if game_over:
            render_text(screen, big_font, "Game Over", (WIDTH // 2, HEIGHT // 2 - 20))
            render_text(screen, font, "Press R to try again", (WIDTH // 2, HEIGHT // 2 + 20))

        pygame.display.flip()


if __name__ == "__main__":
    main()
