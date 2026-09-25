"use client";

import { useState, useRef, useEffect } from "react";
import styles from "./Menu.module.css";
import Image from "next/image";
import { BrigadesPanel } from "./BrigadesPanel";

const Menu = () => {
    const [isOpen, setIsOpen] = useState(false);
    const [activeTab, setActiveTab] = useState("");
    const [usersStage, setUsersStage] = useState(0); // 0=default, 1=wide, 2=tall
    const menuRef = useRef(null);
    const transitionRef = useRef(null);

    const [position, setPosition] = useState({ x: 0, y: 0 });
    const isDragging = useRef(false);
    const dragStart = useRef({ x: 0, y: 0 });

    const handleMouseDown = (e) => {
        if (usersStage !== 2) return;

        const target = e.target;
        if (
            target.tagName === 'BUTTON' || 
            target.tagName === 'INPUT' || 
            target.closest('button') || 
            target.closest(`[class*="Content"]`) || 
            target.closest(`[class*="Search"]`) ||
            target.closest(`[class*="iconImage"]`)
        ) {
            return;
        }
        
        isDragging.current = true;
        dragStart.current = {
            x: e.clientX - position.x,
            y: e.clientY - position.y
        };
        
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
    };

    const handleMouseMove = (e) => {
        if (!isDragging.current) return;
        e.preventDefault();
        setPosition({
            x: e.clientX - dragStart.current.x,
            y: e.clientY - dragStart.current.y
        });
    };

    const handleMouseUp = () => {
        isDragging.current = false;
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
    };

    useEffect(() => {
        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Reset position when not in tall modal mode
    useEffect(() => {
        if (usersStage === 0 || !isOpen) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setPosition({ x: 0, y: 0 });
        }
    }, [usersStage, isOpen]);

    const handleVectorTab = (e) => {
        if (e) e.stopPropagation();
        if (activeTab === "vector") return;

        setUsersStage(1);
        if (transitionRef.current) clearTimeout(transitionRef.current);
        transitionRef.current = setTimeout(() => {
            setUsersStage(0);
            setActiveTab("vector");
        }, 400);
    };

    const handleUsersTab = (e) => {
        if (e) e.stopPropagation();
        if (activeTab === "users") return;

        setActiveTab("users");
        setUsersStage(1);
        if (transitionRef.current) clearTimeout(transitionRef.current);
        transitionRef.current = setTimeout(() => {
            setUsersStage(2);
        }, 400);
    };

    const handleOpen = () => {
        if (!isOpen) {
            setIsOpen(true);
        }
    };

    const handleClose = (e) => {
        e.stopPropagation();
        setIsOpen(false);
        setActiveTab("vector");
        setUsersStage(0);
        if (transitionRef.current) clearTimeout(transitionRef.current);
    };

    return (
        <div
            ref={menuRef}
            className={`${styles.menuContainer} ${isOpen ? styles.open : ""} ${isOpen && usersStage > 0 ? styles.usersWide : ""} ${isOpen && usersStage === 2 ? styles.usersTall : ""}`}
            style={{ transform: `translate(${position.x}px, ${position.y}px)` }}
            onClick={handleOpen}
            onMouseDown={handleMouseDown}
        >
            {/* Toggle Button */}
            {isOpen ? (
                <div className={styles.iconWrapper} onClick={handleClose}>
                    <Image
                        src="/icons/Frame 33.svg"
                        alt="close menu"
                        width={24}
                        height={24}
                        className={styles.icon}
                    />
                </div>
            ) : (
                <div className={styles.iconWrapper}>
                    <Image
                        src="/icons/union.svg"
                        alt="open menu"
                        width={20}
                        height={5}
                        className={styles.icon}
                    />
                </div>
            )}

            {/* Menu Items */}
            <div className={styles.menuItems}>
                <button 
                    className={`${styles.menuButton} ${activeTab === 'vector' ? styles.active : ''}`}
                    onClick={handleVectorTab}
                >
                    <div 
                        className={styles.iconMask} 
                        style={{ WebkitMaskImage: 'url("/icons/Vector 2.svg")', maskImage: 'url("/icons/Vector 2.svg")' }}
                    />
                </button>
                <button 
                    className={`${styles.menuButton} ${activeTab === 'users' ? styles.active : ''}`}
                    onClick={handleUsersTab}
                >
                    <div 
                        className={styles.iconMask} 
                        style={{ WebkitMaskImage: 'url("/icons/icon-users.svg")', maskImage: 'url("/icons/icon-users.svg")' }}
                    />
                </button>
            </div>

            {/* Expanded Users Panel */}
            <div className={styles.usersPanelWrapper}>
                {isOpen && usersStage === 2 && (
                    <BrigadesPanel onClose={handleVectorTab} />
                )}
            </div>
        </div>
    );
};

export default Menu;